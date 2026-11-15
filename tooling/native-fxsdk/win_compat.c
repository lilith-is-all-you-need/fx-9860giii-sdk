#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <io.h>
#include <errno.h>
#include <png.h>
#undef fopen
#undef creat
#undef png_image_begin_read_from_file
#undef png_image_write_to_file

static wchar_t *wide(const char *s) {
    int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,NULL,0);
    if(!n) { errno=EINVAL; return NULL; }
    wchar_t *out=malloc((size_t)n*sizeof *out);
    if(out) MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,s,-1,out,n);
    return out;
}
FILE *fx_wfopen(const char *path,const char *mode) {
    wchar_t *p=wide(path),*m=wide(mode);
    FILE *fp=p&&m?_wfopen(p,m):NULL;
    free(p);free(m);return fp;
}
int fx_creat(const char *path,int mode) {
    wchar_t *p=wide(path);
    int fd=p?_wopen(p,_O_WRONLY|_O_CREAT|_O_TRUNC|_O_BINARY,mode):-1;
    free(p);return fd;
}
int fx_png_read(png_imagep img,const char *path) {
    /* Simplified read retains its stdio stream until finish_read. icon_load
       closes it immediately after png_image_free (success and failure paths). */
    FILE *fp=fx_wfopen(path,"rb");
    if(!fp) { img->warning_or_error=2;snprintf(img->message,sizeof img->message,"Cannot open PNG");return 0; }
    if(!png_image_begin_read_from_stdio(img,fp)) { fclose(fp);return 0; }
    extern FILE *fx_png_stream;
    fx_png_stream=fp;
    return 1;
}
FILE *fx_png_stream;
void fx_png_close(void) { if(fx_png_stream) { fclose(fx_png_stream);fx_png_stream=NULL; } }
int fx_png_write(png_imagep img,const char *path,int linear,const void *buffer,png_int_32 stride,const void *map) {
    FILE *fp=fx_wfopen(path,"wb");
    if(!fp) { img->warning_or_error=2;snprintf(img->message,sizeof img->message,"Cannot create PNG");return 0; }
    int ok=png_image_write_to_stdio(img,fp,linear,buffer,stride,map);
    if(fclose(fp)!=0) ok=0;
    return ok;
}
int fxgxa_main(int,char **);
int wmain(int argc,wchar_t **argv) {
    char **args=calloc((size_t)argc+1,sizeof *args);
    if(!args) return 1;
    for(int i=0;i<argc;i++) {
        int n=WideCharToMultiByte(CP_UTF8,0,argv[i],-1,NULL,0,NULL,NULL);
        args[i]=malloc((size_t)n);
        if(!args[i]) return 1;
        WideCharToMultiByte(CP_UTF8,0,argv[i],-1,args[i],n,NULL,NULL);
    }
    int result=fxgxa_main(argc,args);
    fx_png_close();
    for(int i=0;i<argc;i++) free(args[i]);
    free(args);
    return result;
}
