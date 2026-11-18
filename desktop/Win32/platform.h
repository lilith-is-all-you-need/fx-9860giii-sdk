#pragma once
#include <windows.h>
#include <windowsx.h>
#include <commctrl.h>
#include <commdlg.h>
#include <shlobj.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <wrl/client.h>
#include <objbase.h>
#include <gdiplus.h>
#include <dwmapi.h>
#include <uxtheme.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <json.hpp>
#include <Scintilla.h>
#include <SciLexer.h>

namespace fs = std::filesystem;
using Json = nlohmann::json;
using W = std::wstring;
using Str = std::string;
constexpr UINT WM_ENGINE = WM_APP + 11;
extern HINSTANCE instance;
extern bool english;
inline W tr(const wchar_t *zh, const wchar_t *en) { return english ? en : zh; }
W wide(const Str &value);
Str utf8(const W &value);
W val(const Json &obj, const char *key);
Str readBytes(const fs::path &file, size_t limit = 16 * 1024 * 1024);
void atomicWrite(const fs::path &path, const Str &bytes);
W windowText(HWND w);
void launchFile(HWND owner, const fs::path &path);
void failure(HWND owner, const W &message);
void checkWin(BOOL result, const char *action);
int scaled(HWND w, int value);
HFONT makeFont(HWND w, int height, int weight = FW_NORMAL, const wchar_t *face = L"Segoe UI");
void fill(HDC dc, RECT r, COLORREF color);
void roundBox(HDC dc, RECT r, int radius, COLORREF bg, COLORREF edge);
void drawText(HDC dc, const W &text, RECT r, HFONT font, COLORREF color,
              UINT format = DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS);
fs::path chooseFile(HWND owner, const W &title, const wchar_t *filters, bool save = false, W initial = L"",
                    const wchar_t *extension = nullptr);
fs::path chooseFolder(HWND owner, const W &title);
struct Field {
    W label, value;
    std::vector<W> choices{};
};
bool askFields(HWND owner, const W &title, std::vector<Field> &fields);

class Bridge {
    HANDLE input_ = nullptr, process_ = nullptr, job_ = nullptr;
    std::thread reader_;

  public:
    void start(HWND window, const fs::path &root);
    void send(const Json &command);
    void close();
    ~Bridge() { close(); }
};
inline constexpr COLORREF ink = RGB(26, 44, 52), muted = RGB(75, 96, 105), navy = RGB(21, 45, 50),
                          accent = RGB(13, 109, 91), mint = RGB(135, 229, 192), paper = RGB(255, 255, 255),
                          surface = RGB(242, 246, 246), lineColor = RGB(208, 220, 220);
