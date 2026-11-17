/* SPDX-License-Identifier: MIT
 * Fx Studio's independently implemented source compatibility API.
 * Not the Casio SDK header/library. See README.md for supported semantics. */
#ifndef FXSTUDIO_FXLIB_H
#define FXSTUDIO_FXLIB_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef uint16_t FONTCHARACTER;
typedef struct { int left, top, right, bottom; } DISPBOX;
typedef struct { int width, height; const unsigned char *pBitmap; } GRAPHDATA;
typedef unsigned char WRITEMODIFY;
typedef unsigned char WRITEKIND;
typedef struct { int x, y; GRAPHDATA GraphData; WRITEMODIFY WriteModify; WRITEKIND WriteKind; } DISPGRAPH;
enum { IMB_WRITEMODIFY_NORMAL=1, IMB_WRITEMODIFY_REVERSE=2 };
enum { IMB_WRITEKIND_OVER=1, IMB_WRITEKIND_OR=2, IMB_WRITEKIND_AND=3, IMB_WRITEKIND_XOR=4 };
enum { MINI_OVER=0x10, MINI_OR=0x11, MINI_REV=0x12, MINI_REVOR=0x13 };
enum { KEYWAIT_HALTON_TIMEROFF=0, KEYWAIT_HALTOFF_TIMEROFF=1, KEYWAIT_HALTON_TIMERON=2 };
enum { KEYREP_NOEVENT=0, KEYREP_KEYEVENT=1, KEYREP_TIMEREVENT=2 };
enum { _OPENMODE_READ=1, _OPENMODE_WRITE=2, _OPENMODE_READWRITE=3,
       _OPENMODE_READ_SHARE=0x81, _OPENMODE_READWRITE_SHARE=0x83 };
enum { KEY_CHAR_0='0', KEY_CHAR_1='1', KEY_CHAR_2='2', KEY_CHAR_3='3', KEY_CHAR_4='4',
       KEY_CHAR_5='5', KEY_CHAR_6='6', KEY_CHAR_7='7', KEY_CHAR_8='8', KEY_CHAR_9='9',
       KEY_CHAR_DP='.', KEY_CHAR_EXP=0x0f, KEY_CHAR_PLUS=0x89, KEY_CHAR_MINUS=0x99,
       KEY_CHAR_MULT=0xa9, KEY_CHAR_DIV=0xb9, KEY_CHAR_LPAR='(', KEY_CHAR_RPAR=')',
       KEY_CHAR_PMINUS=0x87, KEY_CHAR_FRAC=0xbb, KEY_CHAR_COMMA=',', KEY_CHAR_STORE=0x0e,
       KEY_CHAR_LOG=0x95, KEY_CHAR_LN=0x85, KEY_CHAR_SIN=0x81, KEY_CHAR_COS=0x82,
       KEY_CHAR_TAN=0x83, KEY_CHAR_SQUARE=0x8b, KEY_CHAR_POW=0xa8, KEY_CHAR_SPACE=' ',
       KEY_CTRL_XTT=30001, KEY_CTRL_EXIT=30002, KEY_CTRL_MENU=30003, KEY_CTRL_EXE=30004,
       KEY_CTRL_SHIFT=30006, KEY_CTRL_ALPHA=30007, KEY_CTRL_OPTN=30008,
       KEY_CTRL_F1=30009, KEY_CTRL_F2=30010, KEY_CTRL_F3=30011, KEY_CTRL_F4=30012,
       KEY_CTRL_F5=30013, KEY_CTRL_F6=30014, KEY_CTRL_AC=30015, KEY_CTRL_VARS=30016,
       KEY_CTRL_UP=30018, KEY_CTRL_LEFT=30020, KEY_CTRL_RIGHT=30021, KEY_CTRL_DOWN=30023,
       KEY_CTRL_DEL=30025, KEY_CTRL_FRACCNVRT=30026, KEY_CTRL_PRGM=30028,
       KEY_CTRL_QUIT=30029, KEY_CTRL_INS=30033, KEY_CTRL_PASTE=30036,
       KEY_CTRL_SETUP=30037, KEY_CTRL_FD=30046, KEY_CTRL_CLIP=30050,
       KEY_CTRL_PAGEUP=30052, KEY_CTRL_PAGEDOWN=30053 };
enum { KEY_CHAR_A='A', KEY_CHAR_B='B', KEY_CHAR_C='C', KEY_CHAR_D='D', KEY_CHAR_E='E',
       KEY_CHAR_F='F', KEY_CHAR_G='G', KEY_CHAR_H='H', KEY_CHAR_I='I', KEY_CHAR_J='J',
       KEY_CHAR_K='K', KEY_CHAR_L='L', KEY_CHAR_M='M', KEY_CHAR_N='N', KEY_CHAR_O='O',
       KEY_CHAR_P='P', KEY_CHAR_Q='Q', KEY_CHAR_R='R', KEY_CHAR_S='S', KEY_CHAR_T='T',
       KEY_CHAR_U='U', KEY_CHAR_V='V', KEY_CHAR_W='W', KEY_CHAR_X='X', KEY_CHAR_Y='Y', KEY_CHAR_Z='Z' };
enum { FXLIB_OK=0, FXLIB_ERR_ARGUMENT=-1000, FXLIB_ERR_UNSUPPORTED=-1001,
       FXLIB_ERR_QUEUE_FULL=-1002, FXLIB_ERR_NO_TIMER=-1003 };
/* Sticky diagnostics: successful calls do not hide an earlier error. */
void fxlib_compat_init(void);
void fxlib_compat_poll(void);
int fxlib_compat_last_error(void);
const char *fxlib_compat_last_function(void);
void fxlib_compat_clear_error(void);
typedef void (*fxlib_error_handler_t)(const char *function, int error);
void fxlib_compat_set_error_handler(fxlib_error_handler_t handler);
int AddIn_main(int isAppli, unsigned short OptionNum);
int fxlib_keycode_to_gint(int code);
int fxlib_keycode_from_gint(int code, int shift, int alpha);

/* All exported names are prefixed to avoid intercepting gint's own OS calls. */
#define Bdisp_AllClr_DD fxlib_Bdisp_AllClr_DD
#define Bdisp_AllClr_VRAM fxlib_Bdisp_AllClr_VRAM
#define Bdisp_AllClr_DDVRAM fxlib_Bdisp_AllClr_DDVRAM
#define Bdisp_AreaClr_DD fxlib_Bdisp_AreaClr_DD
#define Bdisp_AreaClr_VRAM fxlib_Bdisp_AreaClr_VRAM
#define Bdisp_AreaClr_DDVRAM fxlib_Bdisp_AreaClr_DDVRAM
#define Bdisp_AreaReverseVRAM fxlib_Bdisp_AreaReverseVRAM
#define Bdisp_GetDisp_DD fxlib_Bdisp_GetDisp_DD
#define Bdisp_GetDisp_VRAM fxlib_Bdisp_GetDisp_VRAM
#define Bdisp_PutDisp_DD fxlib_Bdisp_PutDisp_DD
#define Bdisp_PutDispArea_DD fxlib_Bdisp_PutDispArea_DD
#define Bdisp_SetPoint_DD fxlib_Bdisp_SetPoint_DD
#define Bdisp_SetPoint_VRAM fxlib_Bdisp_SetPoint_VRAM
#define Bdisp_SetPoint_DDVRAM fxlib_Bdisp_SetPoint_DDVRAM
#define Bdisp_GetPoint_VRAM fxlib_Bdisp_GetPoint_VRAM
#define Bdisp_WriteGraph_DD fxlib_Bdisp_WriteGraph_DD
#define Bdisp_WriteGraph_VRAM fxlib_Bdisp_WriteGraph_VRAM
#define Bdisp_WriteGraph_DDVRAM fxlib_Bdisp_WriteGraph_DDVRAM
#define Bdisp_ReadArea_DD fxlib_Bdisp_ReadArea_DD
#define Bdisp_ReadArea_VRAM fxlib_Bdisp_ReadArea_VRAM
#define Bdisp_DrawLineVRAM fxlib_Bdisp_DrawLineVRAM
#define Bdisp_ClearLineVRAM fxlib_Bdisp_ClearLineVRAM
#define GetVRAMAddress fxlib_GetVRAMAddress
#define locate fxlib_locate
#define Print fxlib_Print
#define PrintRev fxlib_PrintRev
#define PrintC fxlib_PrintC
#define PrintRevC fxlib_PrintRevC
#define PrintLine fxlib_PrintLine
#define PrintRLine fxlib_PrintRLine
#define PrintXY fxlib_PrintXY
#define PrintMini fxlib_PrintMini
#define GetKey fxlib_GetKey
#define GetKeyWait fxlib_GetKeyWait
#define Bkey_GetKeyWait fxlib_Bkey_GetKeyWait
#define IsKeyDown fxlib_IsKeyDown
#define IsKeyUp fxlib_IsKeyUp
#define Bkey_Set_RepeatTime fxlib_Bkey_Set_RepeatTime
#define Bkey_Get_RepeatTime fxlib_Bkey_Get_RepeatTime
#define Bkey_Set_RepeatTime_Default fxlib_Bkey_Set_RepeatTime_Default
#define SetTimer fxlib_SetTimer
#define KillTimer fxlib_KillTimer
#define Sleep fxlib_Sleep
#define RTC_GetTicks fxlib_RTC_GetTicks
#define RTC_Elapsed_ms fxlib_RTC_Elapsed_ms
#define Bfile_OpenFile fxlib_Bfile_OpenFile
#define Bfile_CloseFile fxlib_Bfile_CloseFile
#define Bfile_ReadFile fxlib_Bfile_ReadFile
#define Bfile_WriteFile fxlib_Bfile_WriteFile
#define Bfile_SeekFile fxlib_Bfile_SeekFile
#define Bfile_GetFileSize fxlib_Bfile_GetFileSize
#define Bfile_CreateFile fxlib_Bfile_CreateFile
#define Bfile_DeleteFile fxlib_Bfile_DeleteFile
#define Bfile_CreateDirectory fxlib_Bfile_CreateDirectory
#define Bfile_DeleteDirectory fxlib_Bfile_DeleteDirectory
#define Bfile_StrToName_ncpy fxlib_Bfile_StrToName_ncpy
#define Bfile_NameToStr_ncpy fxlib_Bfile_NameToStr_ncpy
/* An old InitializeSystem() tail may remain in source; gint owns startup. */
#define INIT_ADDIN_APPLICATION(isAppli, optionNum) AddIn_main((isAppli), (optionNum))

void Bdisp_AllClr_DD(void);
void Bdisp_AllClr_VRAM(void);
void Bdisp_AllClr_DDVRAM(void);
void Bdisp_AreaClr_DD(const DISPBOX *area);
void Bdisp_AreaClr_VRAM(const DISPBOX *area);
void Bdisp_AreaClr_DDVRAM(const DISPBOX *area);
void Bdisp_AreaReverseVRAM(int x1,int y1,int x2,int y2);
void Bdisp_GetDisp_DD(unsigned char *data);
void Bdisp_GetDisp_VRAM(unsigned char *data);
void Bdisp_PutDisp_DD(void);
void Bdisp_PutDispArea_DD(const DISPBOX *area);
void Bdisp_SetPoint_DD(int x,int y,unsigned char point);
void Bdisp_SetPoint_VRAM(int x,int y,unsigned char point);
void Bdisp_SetPoint_DDVRAM(int x,int y,unsigned char point);
int Bdisp_GetPoint_VRAM(int x,int y);
void Bdisp_WriteGraph_DD(const DISPGRAPH *graph);
void Bdisp_WriteGraph_VRAM(const DISPGRAPH *graph);
void Bdisp_WriteGraph_DDVRAM(const DISPGRAPH *graph);
void Bdisp_ReadArea_DD(const DISPBOX *area,unsigned char *data);
void Bdisp_ReadArea_VRAM(const DISPBOX *area,unsigned char *data);
void Bdisp_DrawLineVRAM(int x1,int y1,int x2,int y2);
void Bdisp_ClearLineVRAM(int x1,int y1,int x2,int y2);
unsigned char *GetVRAMAddress(void);
void locate(int column,int row);
void Print(const unsigned char *text);
void PrintRev(const unsigned char *text);
void PrintC(const unsigned char *text);
void PrintRevC(const unsigned char *text);
void PrintLine(const unsigned char *text,int last_column);
void PrintRLine(const unsigned char *text,int last_column);
void PrintXY(int x,int y,const unsigned char *text,int reverse);
void PrintMini(int x,int y,const unsigned char *text,int mode);
int GetKey(unsigned int *key);
int GetKeyWait(int mode,int seconds,int menu,unsigned int *key);
int Bkey_GetKeyWait(int *column,int *row,int mode,int seconds,int menu,short *unused);
int IsKeyDown(int key);
int IsKeyUp(int key);
void Bkey_Set_RepeatTime(long first,long next);
void Bkey_Get_RepeatTime(long *first,long *next);
void Bkey_Set_RepeatTime_Default(void);
int SetTimer(int id,int milliseconds,void (*callback)(void));
int KillTimer(int id);
void Sleep(int milliseconds);
int RTC_GetTicks(void);
int RTC_Elapsed_ms(int start,int milliseconds);
int Bfile_OpenFile(const FONTCHARACTER *path,int mode);
int Bfile_CloseFile(int handle);
int Bfile_ReadFile(int handle,void *data,int size,int position);
int Bfile_WriteFile(int handle,const void *data,int size);
int Bfile_SeekFile(int handle,int position);
int Bfile_GetFileSize(int handle);
int Bfile_CreateFile(const FONTCHARACTER *path,int size);
int Bfile_DeleteFile(const FONTCHARACTER *path);
int Bfile_CreateDirectory(const FONTCHARACTER *path);
int Bfile_DeleteDirectory(const FONTCHARACTER *path);
void Bfile_StrToName_ncpy(FONTCHARACTER *dst,const unsigned char *src,int length);
void Bfile_NameToStr_ncpy(unsigned char *dst,const FONTCHARACTER *src,int length);
#ifdef __cplusplus
}
#endif
#endif
