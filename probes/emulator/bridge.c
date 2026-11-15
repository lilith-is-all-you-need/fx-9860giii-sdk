#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include "debug_bridge.h"
#include "emu.h"
#include "g3a.h"
#include "keys.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>

#define BUFFER 32768
#define MAX_BREAKS 128
typedef struct { int type; uint32_t address, size; } Breakpoint;
static Emu *machine;
static SOCKET gdb_listener = INVALID_SOCKET, control_listener = INVALID_SOCKET;
static SOCKET gdb_client = INVALID_SOCKET, control_client = INVALID_SOCKET;
static bool paused = true, quitting, no_ack;
static bool host_keys[256];
static int queued_key = -1, step_budget;
static unsigned signal_number = 5;
static Breakpoint breaks[MAX_BREAKS];
static int break_count;
static bool watch_pending;
static uint32_t watch_address;
static int watch_type;
static char stop_reason[32] = "entry";
static char packet[BUFFER], controls[4096];
static size_t packet_len, controls_len;
static int packet_state;
static unsigned checksum, received_checksum;
static wchar_t frame_path[32768], frame_temp[32768];
static uint16_t latest_frame[396 * 224];
static int frame_width, frame_height;
static uint64_t frame_write_tick;
static bool frame_dirty;
static uint64_t poll_tick, hook_counter;
bool probe_debug_ignore_memory;
static void flush_frame(bool force);

static wchar_t *wide(const char *s)
{
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, NULL, 0);
    if (!n) return NULL;
    wchar_t *w = malloc((size_t)n * sizeof *w);
    if (!w || !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, w, n)) { free(w); return NULL; }
    return w;
}
FILE *probe_utf8_fopen(const char *p, const char *mode)
{
    wchar_t *wp = wide(p), *wm = wide(mode);
    FILE *f = wp && wm ? _wfopen(wp, wm) : NULL;
    free(wp); free(wm); return f;
}
static bool send_all(SOCKET s, const char *p, size_t n)
{
    while (n && s != INVALID_SOCKET) {
        int sent = send(s, p, n > INT_MAX ? INT_MAX : (int)n, 0);
        if (sent <= 0) return false;
        p += sent; n -= (size_t)sent;
    }
    return n == 0;
}
static void rsp(const char *s)
{
    char out[BUFFER + 8]; size_t n = strlen(s); unsigned sum = 0;
    if (n > BUFFER) return;
    out[0] = '$'; memcpy(out+1, s, n);
    for (size_t i=0;i<n;i++) sum += (unsigned char)s[i];
    snprintf(out+n+1, 4, "#%02x", sum & 255);
    send_all(gdb_client, out, n+4);
}
static int hex_digit(char c)
{ return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1; }
static bool hex_u32(const char **p, uint32_t *value)
{
    uint64_t v=0; int count=0, d;
    while ((d=hex_digit(**p))>=0) { if (++count>8) return false; v=v*16+(unsigned)d; ++*p; }
    if (!count) return false;
    *value=(uint32_t)v;
    return true;
}
static void stopped(unsigned sig, const char *reason)
{
    paused=true; step_budget=0; signal_number=sig;
    snprintf(stop_reason,sizeof stop_reason,"%s",reason);
    /* The CPU hook may suspend before the outer run loop gets to
       emu_present(). Publish the hardware display now, without executing
       another instruction or advancing emulated time, before telling GDB. */
    int width, height;
    const uint16_t *screen = emu_screen(machine, &width, &height);
    bridge_frame(screen, width, height);
    flush_frame(true);
    char reply[256];
    if (watch_pending) {
        const char *kind = watch_type==3?"rwatch":watch_type==4?"awatch":"watch";
        snprintf(reply,sizeof reply,"T%02xthread:1;10:%08x;%s:%x;",sig,machine->cpu.pc,kind,watch_address);
        watch_pending=false;
    } else snprintf(reply,sizeof reply,"T%02xthread:1;10:%08x;",sig,machine->cpu.pc);
    rsp(reply);
}
static uint32_t *reg_ptr(unsigned reg)
{
    Cpu *c=&machine->cpu;
    if(reg<16)return &c->r[reg];
    switch(reg) {
        case 16:return &c->pc;case 17:return &c->pr;case 18:return &c->gbr;case 19:return &c->vbr;
        case 20:return &c->mach;case 21:return &c->macl;case 22:return &c->sr;
        case 24:return &c->dsp[0];case 26:return &c->dsp[1];
        case 31:return &c->dsp[2];case 32:return &c->dsp[3];case 33:return &c->dsp[4];case 34:return &c->dsp[5];
        case 40:return &c->mod;case 41:return &c->ssr;case 42:return &c->spc;case 43:return &c->rs;case 44:return &c->re;
        default: if(reg>=51&&reg<=58)return &c->bank[reg-51]; return NULL;
    }
}
static bool set_reg(unsigned reg,uint32_t value)
{
    uint32_t *p=reg_ptr(reg); if(!p)return false;
    if(reg==16) { if(machine->cpu.in_delay_slot || (value&1))return false; machine->cpu.sleeping=false; }
    if(reg==22)cpu_set_sr(&machine->cpu,value);else *p=value;
    return true;
}
/* Debugger memory reads do not invoke MMIO, consume device state or advance time. */
static uint8_t *byte_ptr(uint32_t addr,bool write)
{ return (write?machine->mem.wr:machine->mem.rd)[addr>>PAGE_SHIFT] ? (write?machine->mem.wr:machine->mem.rd)[addr>>PAGE_SHIFT]+(addr&(PAGE_SIZE-1)) : NULL; }
static bool range_valid(uint32_t address,uint32_t size,bool write)
{
    if(size>8192 || (uint64_t)address+size>0x100000000ULL)return false;
    for(uint32_t i=0;i<size;i++)if(!byte_ptr(address+i,write))return false;
    return true;
}
static void resume(bool single,const char *address)
{
    if(machine->cpu.state!=CPU_RUNNING){rsp("E31");return;}
    if(address&&*address){uint32_t a;if(!hex_u32(&address,&a)||*address||!set_reg(16,a)){rsp("E22");return;}}
    paused=false;step_budget=single?1:0;watch_pending=false;strcpy(stop_reason,"running");
}
static void handle_packet(char *p,size_t length)
{
    char reply[BUFFER+1]; uint32_t address,size,value; const char *at;
    if(p[0]!='X'&&memchr(p,0,length)){rsp("E22");return;}
    if(!strcmp(p,"?")){snprintf(reply,sizeof reply,"T%02xthread:1;10:%08x;",signal_number,machine->cpu.pc);rsp(reply);return;}
    if(!strncmp(p,"qSupported",10)){rsp("PacketSize=4000;QStartNoAckMode+;hwbreak+;swbreak+;vContSupported+");return;}
    if(!strcmp(p,"QStartNoAckMode")){rsp("OK");no_ack=true;return;}
    if(!strcmp(p,"qAttached")){rsp("1");return;}
    if(!strcmp(p,"qC")){rsp("QC1");return;}
    if(!strcmp(p,"qfThreadInfo")){rsp("m1");return;}
    if(!strcmp(p,"qsThreadInfo")){rsp("l");return;}
    if(!strncmp(p,"qThreadExtraInfo",16)){rsp("53696e676c652053483420435055");return;}
    if(!strcmp(p,"qOffsets")){rsp("Text=0;Data=0;Bss=0");return;}
    if(p[0]=='H'||p[0]=='T'){rsp("OK");return;}
    if(!strcmp(p,"vCont?")){rsp("vCont;c;s;t");return;}
    if(!strncmp(p,"vCont;c",7)){resume(false,NULL);return;}
    if(!strncmp(p,"vCont;s",7)){resume(true,NULL);return;}
    if(!strncmp(p,"vCont;t",7)){stopped(2,"interrupt");return;}
    if(p[0]=='c'||p[0]=='s'){resume(p[0]=='s',p+1);return;}
    if(!strcmp(p,"D")||!strncmp(p,"D;",2)){rsp("OK");paused=true;return;}
    if(p[0]=='k'||!strncmp(p,"vKill",5)){rsp("OK");quitting=true;return;}
    if(p[0]=='g'&&!p[1]){
        for(unsigned i=0;i<67;i++){uint32_t *r=reg_ptr(i);if(r)snprintf(reply+8*i,9,"%08x",*r);else memcpy(reply+8*i,"xxxxxxxx",8);}
        reply[67*8]=0;rsp(reply);return;
    }
    if(p[0]=='p'){at=p+1;if(!hex_u32(&at,&value)||*at||value>=67){rsp("E22");return;}uint32_t *r=reg_ptr(value);if(r)snprintf(reply,sizeof reply,"%08x",*r);else strcpy(reply,"xxxxxxxx");rsp(reply);return;}
    if(p[0]=='P'){at=p+1;uint32_t r;if(!paused||!hex_u32(&at,&r)||*at++!='='||!hex_u32(&at,&value)||*at||!set_reg(r,value)){rsp("E22");return;}rsp("OK");return;}
    if(p[0]=='G'){rsp("E22");return;}
    if(p[0]=='m'){
        at=p+1;if(!hex_u32(&at,&address)||*at++!=','||!hex_u32(&at,&size)||*at||!range_valid(address,size,false)){rsp("E14");return;}
        for(uint32_t i=0;i<size;i++)snprintf(reply+2*i,3,"%02x",*byte_ptr(address+i,false));
        reply[2*size]=0;rsp(reply);return;
    }
    if(p[0]=='M'||p[0]=='X'){
        at=p+1;if(!paused||!hex_u32(&at,&address)||*at++!=','||!hex_u32(&at,&size)||*at++!=':'||!range_valid(address,size,true)){rsp("E14");return;}
        if(p[0]=='M'){
            if(strlen(at)!=(size_t)size*2){rsp("E22");return;}
            for(uint32_t i=0;i<size*2;i++)if(hex_digit(at[i])<0){rsp("E22");return;}
            for(uint32_t i=0;i<size;i++)*byte_ptr(address+i,true)=(uint8_t)(hex_digit(at[2*i])*16+hex_digit(at[2*i+1]));
        }else{
            size_t available=length-(size_t)(at-p),n=0;unsigned char decoded[8192];
            for(size_t i=0;i<available;i++){unsigned char b=(unsigned char)at[i];if(b=='}'){if(++i==available){rsp("E22");return;}b=(unsigned char)at[i]^0x20;}if(n>=size){rsp("E22");return;}decoded[n++]=b;}
            if(n!=size){rsp("E22");return;}for(uint32_t i=0;i<size;i++)*byte_ptr(address+i,true)=decoded[i];
        }rsp("OK");return;
    }
    if(p[0]=='Z'||p[0]=='z'){
        at=p+1;uint32_t type;
        if(!hex_u32(&at,&type)||*at++!=','||!hex_u32(&at,&address)||*at++!=','||!hex_u32(&at,&size)||*at||type>4||!size||(uint64_t)address+size>0x100000000ULL){rsp("E22");return;}
        if(type<2&&((address&1)||size!=2||!range_valid(address,2,false))){rsp("E22");return;}
        int found=-1;for(int i=0;i<break_count;i++)if(breaks[i].type==(int)type&&breaks[i].address==address&&breaks[i].size==size)found=i;
        if(p[0]=='Z'&&found<0){if(break_count==MAX_BREAKS){rsp("E28");return;}breaks[break_count++]=(Breakpoint){(int)type,address,size};}
        if(p[0]=='z'&&found>=0)breaks[found]=breaks[--break_count];
        rsp("OK");return;
    }
    rsp("");
}
static void gdb_byte(unsigned char b)
{
    if(packet_state==0){if(b==3){if(!paused)stopped(2,"interrupt");return;}if(b=='$'){packet_len=0;checksum=0;packet_state=1;}return;}
    if(packet_state==1){if(b=='#'){packet_state=2;return;}if(packet_len>=BUFFER-1){packet_state=0;send_all(gdb_client,"-",1);return;}packet[packet_len++]=(char)b;checksum=(checksum+b)&255;return;}
    int digit=hex_digit((char)b);if(digit<0){packet_state=0;send_all(gdb_client,"-",1);return;}
    if(packet_state==2){received_checksum=(unsigned)digit*16;packet_state=3;return;}
    received_checksum+=(unsigned)digit;packet_state=0;
    if(received_checksum!=checksum){if(!no_ack)send_all(gdb_client,"-",1);return;}
    if(!no_ack)send_all(gdb_client,"+",1);
    packet[packet_len]=0;handle_packet(packet,packet_len);
}
static void json_escape(const char *p,char *out,size_t cap)
{
    size_t n=0;for(;*p&&n+7<cap;p++){unsigned char c=(unsigned char)*p;if(c=='"'||c=='\\'){out[n++]='\\';out[n++]=(char)c;}else if(c<32){snprintf(out+n,7,"\\u%04x",c);n+=6;}else out[n++]=(char)c;}out[n]=0;
}
/* Strict parser for the documented flat control object. Command/key tokens
   are ASCII identifiers, so escaped or nested values are intentionally rejected. */
static void json_space(const char **p)
{ while(**p==' '||**p=='\t'||**p=='\r'||**p=='\n')++*p; }
static bool json_token(const char **p,char *out,size_t capacity)
{
    if(**p!='"')return false;
    ++*p;size_t n=0;
    while(**p&&**p!='"'){
        unsigned char c=(unsigned char)**p;
        if(c<32||c>=127||c=='\\'||n+1>=capacity)return false;
        out[n++]=*(*p)++;
    }
    if(**p!='"')return false;
    ++*p;out[n]=0;return true;
}
static bool parse_control(const char *p,char command[32],char key[32],bool *down)
{
    unsigned present=0;json_space(&p);if(*p++!='{')return false;json_space(&p);
    for(;;){
        char field[32];if(!json_token(&p,field,sizeof field))return false;
        json_space(&p);if(*p++!=':')return false;json_space(&p);
        unsigned flag;
        if(!strcmp(field,"command")){flag=1;if(!json_token(&p,command,32))return false;}
        else if(!strcmp(field,"key")){flag=2;if(!json_token(&p,key,32))return false;}
        else if(!strcmp(field,"down")){
            flag=4;if(!strncmp(p,"true",4)){*down=true;p+=4;}
            else if(!strncmp(p,"false",5)){*down=false;p+=5;}else return false;
        }else return false;
        if(present&flag)return false;
        present|=flag;json_space(&p);
        if(*p=='}'){p++;break;}if(*p++!=',')return false;json_space(&p);
    }
    json_space(&p);
    return !*p&&(present&1)&&(!strcmp(command,"key")?present==7:present==1);
}
static void control_line(const char *json)
{
    char command[32]={0},key[32]={0},reply[2048],error[1024];bool down=false;
    if(!parse_control(json,command,key,&down)){const char *e="{\"ok\":false,\"error\":\"invalid command object\"}\n";send_all(control_client,e,strlen(e));return;}
    if(!strcmp(command,"status")){
        const char *state=machine->cpu.state==CPU_ERROR?"error":machine->cpu.state==CPU_EXITED?"exited":paused?"paused":"running";
        json_escape(machine->cpu.error,error,sizeof error);
        snprintf(reply,sizeof reply,"{\"ok\":true,\"state\":\"%s\",\"pc\":\"%08X\",\"cycles\":%" PRIu64 ",\"reason\":\"%s\",\"error\":\"%s\"}\n",state,machine->cpu.pc,machine->cpu.instructions,stop_reason,error);
    }else if(!strcmp(command,"key")){
        int k=key_find(key);if(k<0)strcpy(reply,"{\"ok\":false,\"error\":\"unknown key\"}\n");else{host_keys[k]=down;if(down)queued_key=k;else if(queued_key==k)queued_key=-1;strcpy(reply,"{\"ok\":true}\n");}
    }else if(!strcmp(command,"quit")){quitting=true;strcpy(reply,"{\"ok\":true}\n");}
    else strcpy(reply,"{\"ok\":false,\"error\":\"unsupported command\"}\n");
    send_all(control_client,reply,strlen(reply));
}
static void flush_frame(bool force)
{
    if(!frame_dirty||!frame_path[0]||(!force&&GetTickCount64()-frame_write_tick<66))return;
    FILE *f=_wfopen(frame_temp,L"wb");if(!f)return;
    BITMAPFILEHEADER head={0};BITMAPINFOHEADER info={0};
    int stride=(frame_width*3+3)&~3;head.bfType=0x4d42;head.bfOffBits=sizeof head+sizeof info;head.bfSize=head.bfOffBits+stride*frame_height;
    info.biSize=sizeof info;info.biWidth=frame_width;info.biHeight=frame_height;info.biPlanes=1;info.biBitCount=24;info.biCompression=BI_RGB;info.biSizeImage=stride*frame_height;
    bool ok=fwrite(&head,sizeof head,1,f)==1&&fwrite(&info,sizeof info,1,f)==1;uint8_t row[396*3+4];
    for(int y=frame_height-1;y>=0&&ok;y--){memset(row,0,(size_t)stride);for(int x=0;x<frame_width;x++){uint16_t c=latest_frame[y*frame_width+x];row[x*3]=(uint8_t)((c&31)*255/31);row[x*3+1]=(uint8_t)(((c>>5)&63)*255/63);row[x*3+2]=(uint8_t)(((c>>11)&31)*255/31);}ok=fwrite(row,(size_t)stride,1,f)==1;}
    if(fclose(f)!=0)ok=false;
    if(ok&&MoveFileExW(frame_temp,frame_path,MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH)){frame_dirty=false;frame_write_tick=GetTickCount64();}
}
void bridge_frame(const uint16_t *pixels,int w,int h)
{if(w<=0||h<=0||w>396||h>224)return;memcpy(latest_frame,pixels,(size_t)w*h*2);frame_width=w;frame_height=h;frame_dirty=true;flush_frame(false);}
static void disconnect_gdb(void)
{closesocket(gdb_client);gdb_client=INVALID_SOCKET;paused=true;step_budget=0;no_ack=false;packet_state=0;break_count=0;watch_pending=false;strcpy(stop_reason,"disconnected");}
static void bridge_exit(void)
{
    flush_frame(true);
    /* Let final loopback replies drain before WSACleanup tears down sockets. */
    struct linger finish={1,1};
    if(control_client!=INVALID_SOCKET){setsockopt(control_client,SOL_SOCKET,SO_LINGER,(const char *)&finish,sizeof finish);shutdown(control_client,SD_SEND);closesocket(control_client);}
    if(gdb_client!=INVALID_SOCKET){setsockopt(gdb_client,SOL_SOCKET,SO_LINGER,(const char *)&finish,sizeof finish);shutdown(gdb_client,SD_SEND);closesocket(gdb_client);}
    if(control_listener!=INVALID_SOCKET)closesocket(control_listener);
    if(gdb_listener!=INVALID_SOCKET)closesocket(gdb_listener);
    WSACleanup();exit(0);
}
static void pump(unsigned timeout)
{
    if(quitting)bridge_exit();
    fd_set read;FD_ZERO(&read);FD_SET(gdb_listener,&read);FD_SET(control_listener,&read);if(gdb_client!=INVALID_SOCKET)FD_SET(gdb_client,&read);if(control_client!=INVALID_SOCKET)FD_SET(control_client,&read);
    struct timeval tv={(long)(timeout/1000),(long)(timeout%1000*1000)};
    int ready=select(0,&read,NULL,NULL,&tv);if(ready==SOCKET_ERROR){quitting=true;return;}
    if(FD_ISSET(gdb_listener,&read)){SOCKET s=accept(gdb_listener,NULL,NULL);if(gdb_client!=INVALID_SOCKET)closesocket(s);else{gdb_client=s;no_ack=false;packet_state=0;int yes=1;setsockopt(s,IPPROTO_TCP,TCP_NODELAY,(const char*)&yes,sizeof yes);}}
    if(FD_ISSET(control_listener,&read)){SOCKET s=accept(control_listener,NULL,NULL);if(control_client!=INVALID_SOCKET)closesocket(control_client);control_client=s;controls_len=0;}
    char input[4096];
    if(gdb_client!=INVALID_SOCKET&&FD_ISSET(gdb_client,&read)){int n=recv(gdb_client,input,sizeof input,0);if(n<=0)disconnect_gdb();else for(int i=0;i<n;i++)gdb_byte((unsigned char)input[i]);}
    if(control_client!=INVALID_SOCKET&&FD_ISSET(control_client,&read)){
        int n=recv(control_client,input,sizeof input,0);if(n<=0){closesocket(control_client);control_client=INVALID_SOCKET;controls_len=0;memset(host_keys,0,sizeof host_keys);}else for(int i=0;i<n;i++){
            if(input[i]=='\n'){controls[controls_len]=0;control_line(controls);controls_len=0;}
            else if(input[i]!='\r'){if(controls_len+1>=sizeof controls){closesocket(control_client);control_client=INVALID_SOCKET;controls_len=0;break;}controls[controls_len++]=input[i];}
        }
    }
    flush_frame(paused);
    if(quitting)bridge_exit();
}
void probe_debug_poll(Cpu *cpu)
{
    if(!machine)return;
    if(GetTickCount64()-poll_tick>=10){poll_tick=GetTickCount64();pump(0);}
    while(paused&&cpu->sleeping&&!quitting)pump(20);
}
void probe_debug_before(Cpu *cpu,uint32_t address)
{
    if(!machine)return;
    if((++hook_counter&2047)==0)pump(0);
    if(!paused){
        if(watch_pending)stopped(5,"watchpoint");
        else if(step_budget&&--step_budget==0)stopped(5,"step");
        else for(int i=0;i<break_count;i++)if(breaks[i].type<2&&breaks[i].address==address){stopped(5,"breakpoint");break;}
    }
    while(paused&&!quitting)pump(20);
    (void)cpu;
}
void probe_debug_memory(uint32_t address,int size,bool write)
{
    if(!machine||paused||probe_debug_ignore_memory||watch_pending)return;
    for(int i=0;i<break_count;i++){
        Breakpoint *b=&breaks[i];if(b->type<2||(b->type==2&&!write)||(b->type==3&&write))continue;
        if((uint64_t)address<(uint64_t)b->address+b->size&&(uint64_t)address+size>b->address){watch_pending=true;watch_address=address;watch_type=b->type;return;}
    }
}
int bridge_wait_key(uint32_t timeout)
{
    uint64_t end=GetTickCount64()+timeout;
    for(;;){pump(10);while(paused)pump(20);if(queued_key>=0){int k=queued_key;queued_key=-1;return k;}if(timeout!=UINT32_MAX&&GetTickCount64()>=end)return -2;}
}
static SOCKET listener(unsigned *port)
{
    SOCKET s=socket(AF_INET,SOCK_STREAM,IPPROTO_TCP);if(s==INVALID_SOCKET)return s;
    struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);address.sin_port=htons((u_short)*port);
    int exclusive=1;setsockopt(s,SOL_SOCKET,SO_EXCLUSIVEADDRUSE,(const char*)&exclusive,sizeof exclusive);
    if(bind(s,(struct sockaddr*)&address,sizeof address)||listen(s,1)){closesocket(s);return INVALID_SOCKET;}
    int len=sizeof address;getsockname(s,(struct sockaddr*)&address,&len);*port=ntohs(address.sin_port);return s;
}
int bridge_main(int argc,char **argv)
{
    unsigned gp=0,cp=0;const char *path=NULL,*frame=NULL;
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"--gdb-port")&&i+1<argc)gp=(unsigned)strtoul(argv[++i],NULL,10);
        else if(!strcmp(argv[i],"--control-port")&&i+1<argc)cp=(unsigned)strtoul(argv[++i],NULL,10);
        else if(!strcmp(argv[i],"--framebuffer")&&i+1<argc)frame=argv[++i];
        else if(argv[i][0]!='-'&&!path)path=argv[i];else{fprintf(stderr,"invalid argument\n");return 2;}
    }
    if(!path||!frame||gp>65535||cp>65535){fprintf(stderr,"usage: FxEmulator --gdb-port N --control-port M --framebuffer FILE.bmp ADDIN.g1a\n");return 2;}
    wchar_t *wf=wide(frame);if(!wf||wcslen(wf)>32740)return 2;wcscpy(frame_path,wf);swprintf(frame_temp,32768,L"%ls.tmp-%lu",wf,GetCurrentProcessId());free(wf);
    FILE *frame_test=_wfopen(frame_temp,L"wb");
    if(!frame_test){fprintf(stderr,"framebuffer path is not writable\n");return 6;}
    fclose(frame_test);DeleteFileW(frame_temp);
    G3aFile addin={0};if(!g3a_read(path,&addin)||!addin.info.g1a)return 3;
    machine=calloc(1,sizeof *machine);if(!machine||!emu_init(machine,MODEL_FX9750G3)||!g3a_map(machine,&addin))return 4;
    g3a_close(&addin);machine->headless=false;emu_start(machine);
    WSADATA ws;if(WSAStartup(MAKEWORD(2,2),&ws))return 5;
    gdb_listener=listener(&gp);control_listener=listener(&cp);if(gdb_listener==INVALID_SOCKET||control_listener==INVALID_SOCKET){fprintf(stderr,"could not bind loopback listener\n");return 5;}
    setvbuf(stdout,NULL,_IONBF,0);
    printf("{\"event\":\"ready\",\"gdbPort\":%u,\"controlPort\":%u}\n",gp,cp);
    while(!quitting){
        if(machine->cpu.state==CPU_RUNNING){
            /* A running burst always enters a CPU hook before executing. */
            uint64_t slice_start=GetTickCount64();
            emu_update_keys(machine,host_keys);
            emu_run(machine,sh7305_iphi_hz(&machine->hw)/100);
            emu_present(machine);
            if(machine->cpu.state==CPU_EXITED){paused=true;strcpy(stop_reason,"exited");rsp("W00");}
            else if(machine->cpu.state==CPU_ERROR){paused=true;stopped(11,"error");fprintf(stderr,"%s\n",machine->cpu.error);}
            uint64_t elapsed=GetTickCount64()-slice_start;
            if(!paused&&elapsed<10)pump((unsigned)(10-elapsed));
        }else pump(20);
        pump(0);
    }
    return 0;
}
int wmain(int argc,wchar_t **wargv)
{
    char **argv=calloc((size_t)argc+1,sizeof *argv);if(!argv)return 1;
    for(int i=0;i<argc;i++){int n=WideCharToMultiByte(CP_UTF8,0,wargv[i],-1,NULL,0,NULL,NULL);argv[i]=malloc((size_t)n);if(!argv[i])return 1;WideCharToMultiByte(CP_UTF8,0,wargv[i],-1,argv[i],n,NULL,NULL);}
    int status=bridge_main(argc,argv);for(int i=0;i<argc;i++)free(argv[i]);free(argv);return status;
}
