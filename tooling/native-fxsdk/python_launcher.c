/* Small Unicode launcher; invokes only the Python bundled beside this SDK. */
#include <windows.h>
#include <process.h>
#include <stdio.h>
#include <stdlib.h>
#include <wchar.h>
#ifndef SCRIPT
#define SCRIPT L"fxconv-main.py"
#endif
static int append_argument(wchar_t *command,size_t capacity,size_t *used,const wchar_t *arg) {
    size_t size=wcslen(arg);
    if(*used+size*2+4>=capacity) return 0;
    if(*used) command[(*used)++]=L' ';
    command[(*used)++]=L'"';
    size_t slashes=0;
    for(size_t i=0;;i++) {
        wchar_t c=arg[i];
        if(c==L'\\') { slashes++;continue; }
        if(c==L'"'||!c) {
            for(size_t j=0;j<slashes*2+(c==L'"');j++) command[(*used)++]=L'\\';
        } else {
            for(size_t j=0;j<slashes;j++) command[(*used)++]=L'\\';
        }
        slashes=0;
        if(!c) break;
        command[(*used)++]=c;
    }
    command[(*used)++]=L'"';command[*used]=0;
    return 1;
}
int wmain(int argc,wchar_t **argv) {
    wchar_t root[32768],python[32768],script[32768];
    DWORD size=GetModuleFileNameW(NULL,root,32768);
    if(!size||size>=32768) return 127;
    wchar_t *slash=wcsrchr(root,L'\\');
    if(!slash) return 127;
    *slash=0;
    swprintf(script,32768,L"%ls\\%ls",root,SCRIPT);
    DWORD oldsize=GetEnvironmentVariableW(L"PATH",NULL,0);
    wchar_t *old=calloc((size_t)oldsize+1,sizeof *old);
    wchar_t *path=calloc(wcslen(root)+(size_t)oldsize+2,sizeof *path);
    if(!old||!path) return 127;
    GetEnvironmentVariableW(L"PATH",old,oldsize);
    swprintf(path,wcslen(root)+(size_t)oldsize+2,L"%ls;%ls",root,old);
    SetEnvironmentVariableW(L"PATH",path);
    free(old);free(path);
    slash=wcsrchr(root,L'\\');
    if(!slash) return 127;
    *slash=0;
    swprintf(python,32768,L"%ls\\host\\python\\python.exe",root);
    const wchar_t **args=calloc((size_t)argc+5,sizeof *args);
    if(!args) return 127;
    args[0]=python;args[1]=L"-X";args[2]=L"utf8";args[3]=script;
    for(int i=1;i<argc;i++) args[i+3]=argv[i];
    wchar_t *command=calloc(32768,sizeof *command);
    size_t used=0;
    if(!command) return 127;
    for(int i=0;args[i];i++) if(!append_argument(command,32768,&used,args[i])) {
        fwprintf(stderr,L"Bundled Python command exceeds Windows command line limit\n");return 127;
    }
    STARTUPINFOW startup={.cb=sizeof startup};
    PROCESS_INFORMATION child={0};
    BOOL ok=CreateProcessW(python,command,NULL,NULL,TRUE,0,NULL,NULL,&startup,&child);
    free(command);free(args);
    if(!ok) { fwprintf(stderr,L"Cannot start bundled Python (%lu): %ls\n",GetLastError(),python);return 127; }
    WaitForSingleObject(child.hProcess,INFINITE);
    DWORD result=127;GetExitCodeProcess(child.hProcess,&result);
    CloseHandle(child.hThread);CloseHandle(child.hProcess);
    return (int)result;
}
