#pragma once
#include <stdio.h>
#include <fcntl.h>
#include <png.h>
FILE *fx_wfopen(const char *,const char *);
int fx_creat(const char *,int);
int fx_png_read(png_imagep,const char *);
int fx_png_write(png_imagep,const char *,int,const void *,png_int_32,const void *);
void fx_png_close(void);
#define fopen fx_wfopen
#define creat fx_creat
#define png_image_begin_read_from_file fx_png_read
#define png_image_write_to_file fx_png_write
