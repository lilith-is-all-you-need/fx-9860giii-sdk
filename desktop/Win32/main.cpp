#include "studio.h"

namespace {
constexpr wchar_t appClass[] = L"FxStudio.NativeWorkspace";
W caption(const Studio &a) { return a.name.empty() ? L"Fx Studio · Win32" : a.name + L"  —  Fx Studio · Win32"; }
LRESULT CALLBACK keyProc(HWND h, UINT m, WPARAM wp, LPARAM lp, UINT_PTR id, DWORD_PTR data) {
    auto &app = *reinterpret_cast<Studio *>(data);
    try {
        if (m == WM_LBUTTONDOWN || (m == WM_KEYDOWN && wp == VK_SPACE && !(lp & (1u << 30))))
            app.key(static_cast<int>(id), true);
        if (m == WM_LBUTTONUP || m == WM_CAPTURECHANGED || m == WM_CANCELMODE || m == WM_KILLFOCUS ||
            (m == WM_KEYUP && wp == VK_SPACE))
            app.key(static_cast<int>(id), false);
    } catch (const std::exception &e) {
        app.commandError(e);
    }
    return DefSubclassProc(h, m, wp, lp);
}
LRESULT CALLBACK mainProc(HWND h, UINT m, WPARAM wp, LPARAM lp) {
    auto *a = reinterpret_cast<Studio *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
        a = static_cast<Studio *>(reinterpret_cast<CREATESTRUCTW *>(lp)->lpCreateParams);
        a->win = h;
        SetWindowLongPtrW(h, GWLP_USERDATA, (LONG_PTR)a);
    }
    if (!a)
        return DefWindowProcW(h, m, wp, lp);
    try {
        switch (m) {
        case WM_CREATE:
            a->init(h);
            return 0;
        case WM_GETMINMAXINFO: {
            auto *lim = reinterpret_cast<MINMAXINFO *>(lp);
            lim->ptMinTrackSize = {a->unit(830), a->unit(602)};
            return 0;
        }
        case WM_DPICHANGED: {
            auto &r = *reinterpret_cast<RECT *>(lp);
            SetWindowPos(h, nullptr, r.left, r.top, r.right - r.left, r.bottom - r.top, SWP_NOZORDER);
            a->fonts();
            a->layout();
            return 0;
        }
        case WM_SIZE:
            if (wp != SIZE_MINIMIZED && a->tree) {
                a->layout();
            }
            return 0;
        case WM_ERASEBKGND:
            return 1;
        case WM_PAINT: {
            PAINTSTRUCT ps{};
            auto dc = BeginPaint(h, &ps);
            a->paint(dc);
            EndPaint(h, &ps);
            return 0;
        }
        case WM_PRINTCLIENT:
            a->paint(reinterpret_cast<HDC>(wp));
            return 0;
        case WM_CTLCOLORSTATIC:
        case WM_CTLCOLOREDIT:
            if ((HWND)lp == a->output) {
                SetTextColor((HDC)wp, RGB(211, 229, 224));
                SetBkColor((HDC)wp, navy);
                SetDCBrushColor((HDC)wp, navy);
                return (LRESULT)GetStockObject(DC_BRUSH);
            }
            break;
        case WM_DRAWITEM:
            if (auto *d = reinterpret_cast<DRAWITEMSTRUCT *>(lp); d && d->CtlType == ODT_BUTTON) {
                a->buttonDraw(*d);
                return TRUE;
            }
            break;
        case WM_COMMAND:
            if (LOWORD(wp) == Mode)
                return 0;
            if (LOWORD(wp) >= KeyFirst && LOWORD(wp) < KeyFirst + a->keys.size()) {
                if (HIWORD(wp) == BN_CLICKED && !(HWND)lp) {
                    int k = LOWORD(wp) - KeyFirst;
                    a->key(k, true);
                    a->key(k, false);
                }
                return 0;
            }
            if (HIWORD(wp) <= 1 && LOWORD(wp) >= Open)
                a->act(LOWORD(wp));
            return 0;
        case WM_NOTIFY:
            a->notify(reinterpret_cast<NMHDR *>(lp));
            return 0;
        case WM_CONTEXTMENU:
            a->context((HWND)wp, POINT{GET_X_LPARAM(lp), GET_Y_LPARAM(lp)});
            return 0;
        case WM_TIMER:
            if (wp == 1) {
                a->refreshScreen();
                a->idle();
            }
            return 0;
        case WM_ENGINE: {
            std::unique_ptr<Json> msg(reinterpret_cast<Json *>(lp));
            a->event(*msg);
            return 0;
        }
        case WM_LBUTTONDOWN: {
            int x = a->logical(GET_X_LPARAM(lp)), y = a->logical(GET_Y_LPARAM(lp));
            if (abs(x - a->rightArea.x) <= 5 && y >= a->rightArea.y)
                a->splitDrag = 3;
            else if (abs(y - a->inspectArea.y) <= 5 && x < a->rightArea.x)
                a->splitDrag = 2;
            else if (abs(x - a->leftArea.w) <= 5 && y < a->inspectArea.y && y > a->leftArea.y)
                a->splitDrag = 1;
            if (a->splitDrag) {
                SetCapture(h);
                return 0;
            }
            break;
        }
        case WM_MOUSEMOVE: {
            int x = a->logical(GET_X_LPARAM(lp)), y = a->logical(GET_Y_LPARAM(lp));
            RECT r{};
            GetClientRect(h, &r);
            if (a->splitDrag == 1)
                a->side = std::clamp(x, 120, 350);
            if (a->splitDrag == 2)
                a->bottom = std::clamp(a->logical(r.bottom) - y - a->statusArea.h, 120, 420);
            if (a->splitDrag == 3)
                a->right = std::clamp(a->logical(r.right) - x, 250, 410);
            if (a->splitDrag) {
                a->layout();
                return 0;
            }
            break;
        }
        case WM_SETCURSOR:
            if (LOWORD(lp) == HTCLIENT) {
                POINT p{};
                GetCursorPos(&p);
                ScreenToClient(h, &p);
                int x = a->logical(p.x), y = a->logical(p.y);
                if (abs(x - a->rightArea.x) <= 5 ||
                    (abs(x - a->leftArea.w) <= 5 && y < a->inspectArea.y && y > a->leftArea.y)) {
                    SetCursor(LoadCursor(nullptr, IDC_SIZEWE));
                    return TRUE;
                }
                if (abs(y - a->inspectArea.y) <= 5 && x < a->rightArea.x) {
                    SetCursor(LoadCursor(nullptr, IDC_SIZENS));
                    return TRUE;
                }
            }
            break;
        case WM_LBUTTONUP:
            if (a->splitDrag) {
                a->splitDrag = 0;
                ReleaseCapture();
                a->saveConfig();
                return 0;
            }
            break;
        case WM_CAPTURECHANGED:
            a->splitDrag = 0;
            break;
        case WM_ACTIVATE:
            if (LOWORD(wp) == WA_INACTIVE)
                a->keysUp();
            break;
        case WM_DROPFILES: {
            HDROP drop = (HDROP)wp;
            W path(32768, 0);
            auto n = DragQueryFileW(drop, 0, path.data(), (UINT)path.size());
            DragFinish(drop);
            path.resize(n);
            if (n && !a->busy) {
                fs::path p = path;
                W name = p.filename().wstring();
                if (fs::is_directory(p) || name == L"CMakeLists.txt" ||
                    PathMatchSpecW(name.c_str(), L"*.fxide.json;*.fxdebug.json"))
                    a->openProject(p);
                else
                    a->openFile(p);
            }
            return 0;
        }
        case WM_CLOSE:
            a->checkClose();
            return 0;
        case WM_DESTROY:
            KillTimer(h, 1);
            PostQuitMessage(0);
            return 0;
        }
    } catch (const std::exception &e) {
        if (m == WM_CREATE) {
            failure(h, wide(e.what()));
            return -1;
        }
        a->commandError(e);
    }
    return DefWindowProcW(h, m, wp, lp);
}
} // namespace
std::vector<Key> calculatorKeys() {
    return {{L"F1", "F1"},   {L"F2", "F2"},       {L"F3", "F3"},       {L"F4", "F4"},     {L"F5", "F5"},
            {L"F6", "F6"},   {L"SHIFT", "SHIFT"}, {L"OPTN", "OPTN"},   {L"VARS", "VARS"}, {L"MENU", "MENU"},
            {L"◀", "LEFT"},  {L"▲", "UP"},        {L"ALPHA", "ALPHA"}, {L"EXIT", "EXIT"}, {L"DEL", "DEL"},
            {L"AC", "AC"},   {L"▼", "DOWN"},      {L"▶", "RIGHT"},     {L"7", "7"},       {L"8", "8"},
            {L"9", "9"},     {L"×", "MULT"},      {L"÷", "DIV"},       {L"4", "4"},       {L"5", "5"},
            {L"6", "6"},     {L"+", "PLUS"},      {L"−", "MINUS"},     {L"1", "1"},       {L"2", "2"},
            {L"3", "3"},     {L"(", "LPAR"},      {L")", "RPAR"},      {L"0", "0"},       {L".", "DP"},
            {L"(−)", "NEG"}, {L"EXP", "EXP"},     {L"EXE", "EXE"}};
}
Studio::Studio(const fs::path &sdk, const fs::path &dir) : root(sdk), data(dir) {
    fs::create_directories(data);
    if (fs::exists(data / L"settings.json")) {
        auto j = Json::parse(readBytes(data / L"settings.json"), nullptr, false);
        if (j.is_object())
            config = std::move(j);
    }
    english = config.value("language", Str("zh-CN")) == "en";
    side = config.value("left", side);
    right = config.value("right", right);
    bottom = config.value("bottom", bottom);
}
Studio::~Studio() {
    engine.close();
    // SHGetFileInfo returns the shared system image list.
    for (auto f : {font, captionFont, bold, titleFont, bigFont, mono})
        if (f)
            DeleteObject(f);
    if (lexDll)
        FreeLibrary(lexDll);
    if (sciDll)
        FreeLibrary(sciDll);
}
HWND Studio::ctl(const wchar_t *cls, const W &text, DWORD flags, int id, DWORD ex) {
    HWND h = CreateWindowExW(ex, cls, text.c_str(), WS_CHILD | flags, 0, 0, 0, 0, win, (HMENU)(INT_PTR)id, instance,
                             nullptr);
    checkWin(h != nullptr, "Create native control");
    if (font)
        SendMessageW(h, WM_SETFONT, (WPARAM)font, FALSE);
    return h;
}
HWND Studio::button(int id, const W &text) {
    HWND h = ctl(L"BUTTON", text, BS_OWNERDRAW | WS_TABSTOP, id);
    buttons[id] = h;
    return h;
}
void Studio::init(HWND h) {
    creating = true;
    sciDll = LoadLibraryExW((root / L"editor/Scintilla.dll").c_str(), nullptr,
                            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    lexDll = LoadLibraryExW((root / L"editor/Lexilla.dll").c_str(), nullptr,
                            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    checkWin(sciDll && lexDll, "Load bundled native editor");
    fonts();
    tree =
        ctl(WC_TREEVIEWW, L"",
            WS_TABSTOP | TVS_HASBUTTONS | TVS_LINESATROOT | TVS_SHOWSELALWAYS | TVS_FULLROWSELECT | TVS_NOHSCROLL,
            Tree);
    TreeView_SetBkColor(tree, RGB(249, 251, 250));
    TreeView_SetTextColor(tree, ink);
    SetWindowTheme(tree, L"Explorer", nullptr);
    SHFILEINFOW sfi{};
    treeImages = (HIMAGELIST)SHGetFileInfoW(L"folder", FILE_ATTRIBUTE_DIRECTORY, &sfi, sizeof(sfi),
                                            SHGFI_USEFILEATTRIBUTES | SHGFI_SYSICONINDEX | SHGFI_SMALLICON);
    TreeView_SetImageList(tree, treeImages, TVSIL_NORMAL);
    tabs = ctl(WC_TABCONTROLW, L"", TCS_FOCUSONBUTTONDOWN | WS_TABSTOP, Docs);
    sheets = ctl(WC_TABCONTROLW, L"", TCS_FOCUSONBUTTONDOWN | WS_TABSTOP, Inspector);
    output =
        ctl(L"EDIT", L"",
            WS_TABSTOP | WS_VSCROLL | WS_HSCROLL | ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL | ES_AUTOHSCROLL,
            Output);
    SendMessageW(output, EM_SETLIMITTEXT, 1500000, 0);
    SendMessageW(output, WM_SETFONT, (WPARAM)mono, FALSE);
    grid = ctl(WC_LISTVIEWW, L"", LVS_REPORT | LVS_SINGLESEL | LVS_SHOWSELALWAYS | WS_TABSTOP, Grid);
    ListView_SetExtendedListViewStyle(grid, LVS_EX_FULLROWSELECT | LVS_EX_DOUBLEBUFFER | LVS_EX_LABELTIP);
    SetWindowTheme(grid, L"Explorer", nullptr);
    ListView_SetTextColor(grid, ink);
    mode = ctl(WC_COMBOBOXW, L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL, Mode);
    SendMessageW(mode, CB_ADDSTRING, 0, (LPARAM)L"Debug");
    SendMessageW(mode, CB_ADDSTRING, 0, (LPARAM)L"Release");
    SendMessageW(mode, CB_SETCURSEL, 0, 0);
    for (int id : {Open,        Save,      Build,       Start,      Pause,       Stop,        Next,
                   Step,        CloseDoc,  ZoomScreen,  SaveScreen, WelcomeOpen, WelcomeNew,  WelcomeDemo,
                   Refresh,     AddWatch,  RemoveWatch, EditValue,  Inspect,     SelectFrame, RemovePoint,
                   EnablePoint, Condition, Watchpoint,  ReadMem,    WriteMem})
        button(id, L"");
    SetWindowTextW(buttons[CloseDoc], L"×");
    for (int i = 0; i < (int)keys.size(); ++i) {
        auto b = button(KeyFirst + i, keys[i].label);
        SetWindowSubclass(b, keyProc, (UINT_PTR)i, (DWORD_PTR)this);
    }
    theme();
    menus();
    tabNames();
    table();
    status = tr(L"就绪", L"Ready");
    log(tr(L"工作区就绪。", L"Workspace ready."));
    DragAcceptFiles(h, TRUE);
    engine.start(h, root);
    auto opts = config;
    opts["cmd"] = "settings";
    engine.send(opts);
    if (initial.empty() && config.contains("last"))
        initial = val(config, "last");
    if (!initial.empty() && fs::exists(initial))
        openProject(initial);
    SetTimer(h, 1, 110, nullptr);
    creating = false;
    layout();
    enable();
}
void Studio::fonts() {
    auto old = std::array{font, captionFont, bold, titleFont, bigFont, mono};
    font = makeFont(win, 14);
    captionFont = makeFont(win, 12);
    bold = makeFont(win, 14, FW_SEMIBOLD);
    titleFont = makeFont(win, 24, FW_SEMIBOLD);
    bigFont = makeFont(win, 27, FW_SEMIBOLD);
    mono = makeFont(win, 13, FW_NORMAL, L"Consolas");
    if (tree) {
        for (HWND h : {tree, tabs, sheets, grid, mode})
            SendMessageW(h, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(output, WM_SETFONT, (WPARAM)mono, TRUE);
    }
    for (auto &b : buttons)
        SendMessageW(b.second, WM_SETFONT, (WPARAM)font, FALSE);
    for (auto f : old)
        if (f)
            DeleteObject(f);
}
void Studio::theme() {
    const std::map<int, W> labels = {{Open, tr(L"打开", L"Open")},
                                     {Save, tr(L"保存", L"Save")},
                                     {Build, tr(L"构建", L"Build")},
                                     {Start, tr(L"调试", L"Debug")},
                                     {Pause, tr(L"暂停", L"Pause")},
                                     {Stop, tr(L"停止", L"Stop")},
                                     {Next, tr(L"逐过程", L"Step over")},
                                     {Step, tr(L"逐语句", L"Step into")},
                                     {ZoomScreen, tr(L"放大屏幕", L"Zoom LCD")},
                                     {SaveScreen, tr(L"保存 PNG", L"Save PNG")},
                                     {WelcomeOpen, tr(L"打开工程…", L"Open project…")},
                                     {WelcomeNew, tr(L"新建工程…", L"New project…")},
                                     {WelcomeDemo, tr(L"打开计数器示例", L"Open counter example")},
                                     {Refresh, tr(L"刷新", L"Refresh")},
                                     {AddWatch, tr(L"添加监视", L"Add watch")},
                                     {RemoveWatch, tr(L"移除", L"Remove")},
                                     {EditValue, tr(L"修改值", L"Edit value")},
                                     {Inspect, tr(L"查看成员", L"Inspect")},
                                     {SelectFrame, tr(L"选择栈帧", L"Select frame")},
                                     {RemovePoint, tr(L"移除断点", L"Remove")},
                                     {EnablePoint, tr(L"启用 / 禁用", L"Enable / disable")},
                                     {Condition, tr(L"条件", L"Condition")},
                                     {Watchpoint, tr(L"数据断点", L"Watchpoint")},
                                     {ReadMem, tr(L"读取…", L"Read…")},
                                     {WriteMem, tr(L"写入…", L"Write…")}};
    for (auto &[id, s] : labels)
        SetWindowTextW(buttons.at(id), s.c_str());
}
void Studio::place(HWND h, int x, int y, int w, int height, bool show) {
    if (!h)
        return;
    if (!show) {
        ShowWindow(h, SW_HIDE);
        return;
    }
    SetWindowPos(h, nullptr, unit(x), unit(y), std::max(1, unit(x + w) - unit(x)),
                 std::max(1, unit(y + height) - unit(y)), SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW);
}
void Studio::layout() {
    if (!tree || !output || creating)
        return;
    RECT rect{};
    GetClientRect(win, &rect);
    int w = logical(rect.right), h = logical(rect.bottom);
    int rp = std::clamp(right, 250, std::max(250, w - 530));
    int left = std::clamp(side, 120, std::max(120, w - rp - 260));
    int low = std::clamp(bottom, 116, std::max(116, h - 338));
    int split = w - rp, top = 107, sy = h - 27 - low;
    topArea = {0, 0, w, 55};
    toolsArea = {0, 55, w, 52};
    leftArea = {0, top, left, sy - top};
    rightArea = {split, top, rp, h - top - 27};
    inspectArea = {0, sy, split, low};
    statusArea = {0, h - 27, w, 27};
    editorArea = {left + 4, top, split - left - 8, sy - top};
    place(buttons[Open], 12, 66, 60, 29);
    place(buttons[Save], 77, 66, 59, 29);
    place(mode, 151, 66, 90, 200);
    int tx = 252;
    for (auto [id, bw] : std::array<std::pair<int, int>, 6>{
             {{Build, 68}, {Start, 80}, {Pause, 60}, {Stop, 59}, {Next, 80}, {Step, 78}}}) {
        place(buttons[id], tx, 65, bw, 31);
        tx += bw + 5;
    }
    place(tree, 5, top + 38, left - 9, sy - top - 40);
    int ex = editorArea.x + 2, ew = editorArea.w - 4;
    place(tabs, ex, top + 3, ew - 29, 30, !files.empty());
    place(buttons[CloseDoc], ex + ew - 25, top + 4, 24, 23, !files.empty());
    for (int i = 0; i < (int)files.size(); ++i)
        place(files[i]->editor, ex, top + 35, ew, sy - top - 39, i == selected);
    welcome = {ex, top, ew, sy - top};
    int by = top + std::max(65, (sy - top) / 2) + 14;
    int wb = std::min(121, (ew - 28) / 2);
    place(buttons[WelcomeOpen], ex + (ew - 2 * wb - 8) / 2, by, wb, 34, files.empty());
    place(buttons[WelcomeNew], ex + (ew - 2 * wb - 8) / 2 + wb + 8, by, wb, 34, files.empty());
    place(buttons[WelcomeDemo], ex + (ew - 157) / 2, by + 43, 157, 27, files.empty());
    place(sheets, 7, sy + 6, split - 15, 28);
    int contentTop = sy + 37;
    for (int id : {Refresh, AddWatch, RemoveWatch, EditValue, Inspect, SelectFrame, RemovePoint, EnablePoint,
                   Condition, Watchpoint, ReadMem, WriteMem})
        ShowWindow(buttons[id], SW_HIDE);
    int ax = 10;
    for (int id : actions) {
        int width = english ? 102 : 89;
        if (id == EnablePoint)
            width = english ? 118 : 103;
        place(buttons[id], ax, contentTop, width, 25);
        ax += width + 5;
    }
    if (!actions.empty())
        contentTop += 30;
    place(output, 9, contentTop, split - 18, h - 27 - contentTop - 7, sheet == Logs);
    place(grid, 7, contentTop, split - 15, h - 27 - contentTop - 6, sheet != Logs);
    int inset = 15;
    int screenW = std::min(rp - inset * 2, 320);
    int screenH = screenW / 2;
    // Reserve sufficient space for all seven key rows on compact windows.
    screenH = std::max(68, std::min(screenH, (h - top - 168) / 2));
    screenW = screenH * 2;
    lcd = {split + (rp - screenW) / 2, top + 48, screenW, screenH};
    int iy = lcd.y + lcd.h + 12;
    place(buttons[ZoomScreen], split + inset, iy, (rp - inset * 2 - 6) / 2, 26);
    place(buttons[SaveScreen], split + rp / 2 + 3, iy, (rp - inset * 2 - 6) / 2, 26);
    iy += 51;
    int kh = std::clamp((h - 27 - iy - 7 * 4 - 10) / 7, 19, 38);
    for (int i = 0; i < (int)keys.size(); ++i) {
        int row = i < 18 ? i / 6 : 3 + (i - 18) / 5, col = i < 18 ? i % 6 : (i - 18) % 5, n = i < 18 ? 6 : 5;
        int usable = rp - 2 * inset + 4;
        int x = split + inset + col * usable / n;
        place(buttons[KeyFirst + i], x, iy + row * (kh + 4), ((col + 1) * usable / n) - (col * usable / n) - 4, kh);
    }
    if (sheet != Logs && grid) {
        HWND header = ListView_GetHeader(grid);
        int count = Header_GetItemCount(header);
        if (count > 0) {
            int tw = unit(split - 37);
            int used = 0;
            for (int i = 0; i < count; ++i) {
                int col = i == count - 1 ? tw - used : (count == 2 ? tw * 34 / 100 : tw / count);
                ListView_SetColumnWidth(grid, i, col);
                used += col;
            }
        }
    }
    InvalidateRect(win, nullptr, FALSE);
}
void Studio::paint(HDC dc) {
    RECT client{};
    GetClientRect(win, &client);
    auto r = [&](int x, int y, int w, int h) { return RECT{unit(x), unit(y), unit(x + w), unit(y + h)}; };
    auto region = [&](Area a, COLORREF c) { fill(dc, r(a.x, a.y, a.w, a.h), c); };
    auto text = [&](const W &s, int x, int y, int w, int h, HFONT f, COLORREF c,
                    UINT flags = DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS) {
        drawText(dc, s, r(x, y, w, h), f, c, flags);
    };
    fill(dc, client, paper);
    region(topArea, navy);
    region(toolsArea, surface);
    region(leftArea, RGB(249, 251, 250));
    region(rightArea, RGB(248, 251, 250));
    region(inspectArea, paper);
    region(statusArea, navy);
    if (!tree)
        return;
    int iw = logical(client.right);
    HICON ico = LoadIconW(instance, MAKEINTRESOURCEW(101));
    DrawIconEx(dc, unit(16), unit(10), ico, unit(35), unit(35), 0, nullptr, DI_NORMAL);
    auto previousFont = SelectObject(dc, titleFont);
    SIZE titleSize{};
    GetTextExtentPoint32W(dc, L"Fx Studio", 9, &titleSize);
    SelectObject(dc, previousFont);
    int titleWidth = logical(titleSize.cx) + 3;
    int divider = 59 + titleWidth + 17;
    text(L"Fx Studio", 59, 0, titleWidth, 54, titleFont, paper, DT_SINGLELINE | DT_VCENTER);
    fill(dc, r(divider, 17, 1, 22), RGB(66, 94, 94));
    text(L"fx-9860GIII", divider + 16, 0, 120, 54, font, RGB(191, 216, 209));
    W state = busy   ? tr(L"处理中", L"Working")
              : live ? (paused ? tr(L"已暂停", L"Paused") : tr(L"运行中", L"Running"))
                     : tr(L"离线工作区", L"Offline workspace");
    text(state, iw - 232, 0, 214, 54, bold, mint, DT_RIGHT | DT_SINGLELINE | DT_VCENTER);
    fill(dc, r(0, 106, iw, 1), lineColor);
    fill(dc, r(leftArea.w, leftArea.y, 1, leftArea.h), lineColor);
    fill(dc, r(rightArea.x - 2, rightArea.y, 1, rightArea.h), lineColor);
    fill(dc, r(0, inspectArea.y, inspectArea.w, 1), lineColor);
    text(tr(L"工程文件", L"Project files"), 15, leftArea.y, leftArea.w - 20, 37, bold, ink);
    text(tr(L"计算器", L"Calculator"), rightArea.x + 15, rightArea.y, 120, 40, bold, ink);
    text(L"128 × 64", rightArea.x + rightArea.w - 95, rightArea.y, 79, 40, captionFont, muted,
         DT_RIGHT | DT_SINGLELINE | DT_VCENTER);
    auto frame = r(lcd.x - 3, lcd.y - 3, lcd.w + 6, lcd.h + 6);
    roundBox(dc, frame, unit(6), RGB(69, 88, 81), RGB(56, 76, 70));
    RECT panel = r(lcd.x, lcd.y, lcd.w, lcd.h);
    fill(dc, panel, RGB(215, 225, 206));
    if (bitmap) {
        Gdiplus::Graphics graphics(dc);
        graphics.SetInterpolationMode(Gdiplus::InterpolationModeNearestNeighbor);
        graphics.SetPixelOffsetMode(Gdiplus::PixelOffsetModeHalf);
        int zoom =
            std::max(1, std::min((int)(panel.right - panel.left) / 128, (int)(panel.bottom - panel.top) / 64));
        graphics.DrawImage(bitmap.get(), (panel.left + panel.right - 128 * zoom) / 2,
                           (panel.top + panel.bottom - 64 * zoom) / 2, 128 * zoom, 64 * zoom);
    } else {
        text(tr(L"等待调试", L"Awaiting debugger"), lcd.x, lcd.y, lcd.w, lcd.h, font, RGB(72, 92, 76),
             DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    }
    text(tr(L"按键", L"Keypad"), rightArea.x + 15, lcd.y + lcd.h + 40, rightArea.w - 24, 22, captionFont, muted);
    if (files.empty()) {
        auto a = welcome;
        int middle = a.y + std::max(65, a.h / 2);
        text(tr(L"开发工作区", L"Development workspace"), a.x + 5, middle - 72, a.w - 10, 40, bigFont, ink,
             DT_SINGLELINE | DT_CENTER | DT_VCENTER);
        text(tr(L"打开 CMake 工程，或从 C / C++ 模板开始。",
                L"Open a CMake project or start from a C / C++ template."),
             a.x + 4, middle - 31, a.w - 8, 30, font, muted,
             DT_SINGLELINE | DT_CENTER | DT_VCENTER | DT_END_ELLIPSIS);
    }
    text(status, 14, statusArea.y, statusArea.w - 295, 27, captionFont, RGB(225, 237, 233));
    W caret;
    if (doc()) {
        int pos = (int)edit(SCI_GETCURRENTPOS);
        int row = (int)edit(SCI_LINEFROMPOSITION, pos) + 1, col = (int)edit(SCI_GETCOLUMN, pos) + 1;
        caret = tr(L"行 ", L"Ln ") + std::to_wstring(row) + tr(L"  列 ", L"  Col ") + std::to_wstring(col) +
                L"     UTF-8";
    }
    text(caret, iw - 280, statusArea.y, 264, 27, captionFont, RGB(196, 218, 209),
         DT_RIGHT | DT_SINGLELINE | DT_VCENTER);
}
void Studio::buttonDraw(DRAWITEMSTRUCT &d) {
    int id = d.CtlID;
    bool off = (d.itemState & ODS_DISABLED) != 0, pressed = (d.itemState & ODS_SELECTED) != 0;
    bool primary = id == Start || id == WelcomeOpen || id == KeyFirst + 37;
    bool keycap = id >= KeyFirst;
    bool selectedKey = keycap && held.count(id - KeyFirst);
    COLORREF bg = primary ? accent : paper, edge = primary ? accent : lineColor, fg = primary ? paper : ink;
    if (keycap && id < KeyFirst + 6) {
        bg = RGB(226, 239, 233);
        edge = RGB(204, 221, 211);
        fg = RGB(37, 82, 67);
    }
    if (off) {
        bg = keycap ? RGB(241, 245, 243) : RGB(238, 243, 241);
        edge = RGB(220, 229, 225);
        fg = RGB(117, 135, 128);
    }
    if (pressed || selectedKey) {
        bg = primary ? RGB(12, 81, 66) : RGB(197, 224, 213);
    }
    RECT rect = d.rcItem;
    fill(d.hDC, rect, keycap ? RGB(248, 251, 250) : surface);
    roundBox(d.hDC, rect, unit(8), bg, edge);
    W label = windowText(d.hwndItem);
    if (id == Open || id == Save || id == Build || id == Start || id == Pause || id == Stop) {
        SIZE size{};
        auto previous = SelectObject(d.hDC, font);
        GetTextExtentPoint32W(d.hDC, label.c_str(), static_cast<int>(label.size()), &size);
        SelectObject(d.hDC, previous);
        int gap = unit(5), sideLength = unit(13),
            x = std::max<int>(rect.left + unit(3), (rect.left + rect.right - size.cx - gap - sideLength) / 2);
        int y = (rect.top + rect.bottom - sideLength) / 2;
        Gdiplus::Graphics g(d.hDC);
        g.SetSmoothingMode(Gdiplus::SmoothingModeAntiAlias);
        g.TranslateTransform(static_cast<float>(x), static_cast<float>(y));
        g.ScaleTransform(sideLength / 16.0f, sideLength / 16.0f);
        Gdiplus::Color color(255, GetRValue(fg), GetGValue(fg), GetBValue(fg));
        Gdiplus::Pen pen(color, 1.6f);
        Gdiplus::SolidBrush brush(color);
        if (id == Open) {
            Gdiplus::Point outline[] = {{1, 4}, {6, 4}, {8, 6}, {14, 6}, {14, 13}, {1, 13}, {1, 4}};
            g.DrawLines(&pen, outline, 7);
        }
        if (id == Save) {
            Gdiplus::Point outline[] = {{2, 2}, {11, 2}, {14, 5}, {14, 14}, {2, 14}, {2, 2}};
            g.DrawLines(&pen, outline, 6);
            g.DrawRectangle(&pen, 5, 8, 6, 5);
            g.DrawLine(&pen, 5, 3, 9, 3);
        }
        if (id == Build) {
            g.DrawLine(&pen, 3, 13, 11, 5);
            g.DrawLine(&pen, 7, 2, 14, 9);
            g.DrawLine(&pen, 5, 4, 8, 1);
        }
        if (id == Start) {
            Gdiplus::Point pts[] = {{3, 1}, {14, 8}, {3, 15}};
            g.FillPolygon(&brush, pts, 3);
        }
        if (id == Pause) {
            g.FillRectangle(&brush, 3, 2, 3, 12);
            g.FillRectangle(&brush, 10, 2, 3, 12);
        }
        if (id == Stop)
            g.FillRectangle(&brush, 3, 3, 10, 10);
        rect.left = x + sideLength + gap;
        drawText(d.hDC, label, rect, font, fg, DT_LEFT | DT_SINGLELINE | DT_VCENTER);
        rect = d.rcItem;
    } else
        drawText(d.hDC, label, rect, keycap ? (id < KeyFirst + 18 ? captionFont : bold) : font, fg,
                 DT_CENTER | DT_SINGLELINE | DT_VCENTER);
    if (d.itemState & ODS_FOCUS) {
        InflateRect(&rect, -unit(3), -unit(3));
        DrawFocusRect(d.hDC, &rect);
    }
}
void Studio::note(const W &text) {
    status = text;
    RECT r{0, unit(statusArea.y), unit(statusArea.w), unit(statusArea.y + statusArea.h)};
    InvalidateRect(win, &r, FALSE);
}
void Studio::log(const W &text) {
    W clean;
    for (auto c : text)
        if (c != L'\r') {
            if (c == L'\n')
                clean += L'\r';
            clean += c;
        }
    clean += L"\r\n";
    logText += clean;
    if (logText.size() > 260000) {
        auto p = logText.find(L'\n', logText.size() - 190000);
        logText.erase(0, p == W::npos ? 0 : p + 1);
        SetWindowTextW(output, logText.c_str());
    } else {
        SendMessageW(output, EM_SETSEL, static_cast<WPARAM>(-1), -1);
        SendMessageW(output, EM_REPLACESEL, FALSE, (LPARAM)clean.c_str());
    }
    SendMessageW(output, EM_SCROLLCARET, 0, 0);
}
void Studio::saveConfig() {
    config["language"] = english ? "en" : "zh-CN";
    config["left"] = side;
    config["right"] = right;
    config["bottom"] = bottom;
    if (!quietSettings)
        atomicWrite(data / L"settings.json", config.dump(2));
}
void Studio::showError(const W &msg) {
    note(msg);
    log(msg);
    setSheet(Logs);
    MessageBeep(MB_ICONWARNING);
}
void Studio::commandError(const std::exception &e) {
    try {
        showError(wide(e.what()));
    } catch (...) {
        showError(tr(L"操作失败。", L"Operation failed."));
    }
}
void Studio::request(Str cmd, Json a) {
    if (busy || engineDown)
        return;
    hadError = false;
    a["cmd"] = cmd;
    engine.send(a);
    currentCmd = cmd;
    busy = true;
    assetLock = cmd == "asset" || cmd == "migrate";
    enable();
}
void Studio::scheduleSnapshot(bool navigate) {
    snapshotWanted = true;
    navigateNext = navigateNext || navigate;
}
void Studio::idle() {
    if (shutting || engineDown || busy)
        return;
    if (closing) {
        shutdown();
        return;
    }
    if (ended) {
        ended = false;
        request("stop");
        return;
    }
    if (autoDebug && !project.empty()) {
        autoDebug = false;
        act(Start);
        return;
    }
    if (snapshotWanted && live && paused) {
        snapshotWanted = false;
        snapNavigation = navigateNext;
        navigateNext = false;
        Json args;
        args["watches"] = Json::array();
        for (auto &w : watches)
            args["watches"].push_back(utf8(w));
        request("snapshot", args);
    }
}
void Studio::checkClose() {
    if (closing)
        return;
    if (!confirm())
        return;
    if (busy) {
        closing = true;
        if (!assetLock)
            engine.send({{"cmd", "cancel"}});
        note(tr(L"正在结束当前操作…", L"Finishing the current operation…"));
        return;
    }
    shutdown();
}
void Studio::shutdown() {
    if (shutting)
        return;
    shutting = true;
    keysUp();
    saveSession();
    saveConfig();
    engine.close();
    MSG m{};
    while (PeekMessageW(&m, win, WM_ENGINE, WM_ENGINE, PM_REMOVE))
        delete reinterpret_cast<Json *>(m.lParam);
    DestroyWindow(win);
}
void Studio::key(int index, bool down) {
    if (!live || engineDown || index < 0 || index >= (int)keys.size())
        return;
    if (down ? !held.insert(index).second : !held.erase(index))
        return;
    engine.send({{"cmd", "key"}, {"key", keys[index].code}, {"down", down}});
    InvalidateRect(buttons[KeyFirst + index], nullptr, FALSE);
}
void Studio::keysUp() {
    auto copy = held;
    for (int k : copy)
        key(k, false);
    held.clear();
}
void Studio::refreshScreen() {
    if (framebuffer.empty() || !live)
        return;
    WIN32_FILE_ATTRIBUTE_DATA info{};
    if (!GetFileAttributesExW(framebuffer.c_str(), GetFileExInfoStandard, &info) ||
        CompareFileTime(&info.ftLastWriteTime, &frameTime) == 0)
        return;
    try {
        auto image = loadImage(framebuffer, true);
        if (image && image->GetWidth() == 128 && image->GetHeight() == 64) {
            bitmap = std::move(image);
            frameTime = info.ftLastWriteTime;
            RECT r{unit(lcd.x), unit(lcd.y), unit(lcd.x + lcd.w), unit(lcd.y + lcd.h)};
            InvalidateRect(win, &r, FALSE);
            EnableWindow(buttons[SaveScreen], TRUE);
            EnableWindow(buttons[ZoomScreen], TRUE);
        }
    } catch (const std::exception &) { /* A framebuffer may be between two publications. */
    }
}
void Studio::event(const Json &msg) {
    auto kind = msg.value("kind", Str());
    const auto &d = msg.at("data");
    if (kind == "log") {
        log(wide(d.get<Str>()));
    } else if (kind == "diagnostic") {
        diagnostics.push_back(d);
        if (sheet == Problems)
            table(true);
    } else if (kind == "project") {
        opened(d);
        SetWindowTextW(win, caption(*this).c_str());
    } else if (kind == "artifact") {
        g1a = val(d, "g1a");
        auto info = tr(L"构建产物已校验", L"Build verified") + L" · " + val(d, "configuration") + L" · " +
                    val(d, "size") + L" B";
        note(info);
        log(info + L"\r\nELF   " + val(d, "elf") + L"\r\nG1A   " + g1a.wstring());
    } else if (kind == "framebuffer") {
        live = true;
        framebuffer = wide(d.get<Str>());
        frameTime = {};
        bitmap.reset();
        refreshScreen();
    } else if (kind == "state") {
        Str state = d.get<Str>();
        paused = false;
        live = state != "idle";
        execLine = 0;
        execFile.clear();
        for (auto &f : files) {
            SendMessageW(f->editor, SCI_MARKERDELETEALL, 2, 0);
            SendMessageW(f->editor, SCI_MARKERDELETEALL, 3, 0);
        }
        if (!live) {
            framebuffer.clear();
            held.clear();
            snapshot = Json::object();
            memory = nullptr;
            snapshotWanted = false;
            for (auto &p : points) {
                p.number.clear();
                p.status.clear();
            }
            table();
        }
        note(live ? tr(L"运行中", L"Running") : tr(L"调试已停止", L"Debugger stopped"));
        enable();
    } else if (kind == "paused") {
        live = paused = true;
        stopReason = val(d, "reason");
        pc = val(d, "pc");
        note(tr(L"已暂停", L"Paused") + L" · " + stopReason + L" · " + pc);
        scheduleSnapshot(true);
        enable();
    } else if (kind == "ended") {
        ended = true;
        note(tr(L"会话已结束", L"Session ended"));
    } else if (kind == "snapshot" && paused) {
        snapshot = d;
        if (d.contains("frame")) {
            auto f = d["frame"];
            execFile = val(f, "localPath");
            execLine = f.value("line", Json(nullptr)).is_number() ? f["line"].get<int>() : 0;
            if (snapNavigation && execLine > 0 && fs::is_regular_file(execFile))
                openFile(execFile, execLine);
            for (auto &file : files)
                markers(*file);
        }
        table(true);
        refreshScreen();
    } else if (kind == "point") {
        for (auto &p : points)
            if (p.id == d.value("id", -1)) {
                p.number = val(d, "number");
                p.status = val(d, "status");
            }
        if (sheet == Points)
            table(true);
    } else if (kind == "memory") {
        memory = d;
        setSheet(Memory);
    } else if (kind == "value") {
        log(wide(d.get<Str>()));
        scheduleSnapshot(false);
    } else if (kind == "children") {
        inspectMembers(d);
    } else if (kind == "exported") {
        note(tr(L"已导出", L"Exported") + L" · " + wide(d.get<Str>()));
    } else if (kind == "assets") {
        g1a.clear();
        refreshFiles();
        reloadTree();
        W header = val(d, "header");
        if (!header.empty() && fs::exists(header))
            openFile(header);
        note(tr(L"已更新资源与构建配置", L"Resources and build rules updated"));
    } else if (kind == "error") {
        hadError = true;
        showError(wide(d.get<Str>()));
    } else if (kind == "cancelled") {
        hadError = true;
        note(tr(L"操作已取消", L"Operation cancelled"));
    } else if (kind == "done" && d == currentCmd) {
        Str prev = currentCmd;
        currentCmd.clear();
        busy = assetLock = false;
        if (!hadError && (prev == "register" || prev == "evaluate" || prev == "write" || prev == "frame"))
            scheduleSnapshot(prev == "frame");
        if (hadError && (prev == "open" || prev == "start"))
            autoDebug = false;
        enable();
        if (closing) {
            shutdown();
            return;
        }
        idle();
    } else if (kind == "disconnected" && !shutting) {
        engineDown = true;
        live = paused = busy = false;
        showError(tr(L"SDK 后台已退出。请重新打开工作台。", L"The SDK host exited. Reopen the workspace."));
        enable();
        if (closing)
            shutdown();
    }
}
int WINAPI wWinMain(HINSTANCE inst, HINSTANCE, PWSTR, int show) {
    instance = inst;
    SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    INITCOMMONCONTROLSEX cc{sizeof(cc),
                            ICC_STANDARD_CLASSES | ICC_TREEVIEW_CLASSES | ICC_LISTVIEW_CLASSES | ICC_TAB_CLASSES};
    InitCommonControlsEx(&cc);
    Gdiplus::GdiplusStartupInput gp;
    ULONG_PTR token{};
    Gdiplus::GdiplusStartup(&token, &gp, nullptr);
    int code = 1;
    try {
        W exe(32768, 0);
        exe.resize(GetModuleFileNameW(nullptr, exe.data(), (DWORD)exe.size()));
        fs::path base = fs::path(exe).parent_path() / L"Studio";
        PWSTR local{};
        if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &local)))
            throw std::runtime_error("LocalAppData unavailable.");
        fs::path user = fs::path(local) / L"FxStudioWin32";
        CoTaskMemFree(local);
        fs::path init;
        W lang;
        bool debug = false;
        int argc{};
        auto argv = CommandLineToArgvW(GetCommandLineW(), &argc);
        for (int i = 1; i < argc; ++i) {
            W p = argv[i];
            if (p == L"--sdk-root" && i + 1 < argc)
                base = argv[++i];
            else if (p == L"--settings-dir" && i + 1 < argc)
                user = argv[++i];
            else if (p == L"--language" && i + 1 < argc)
                lang = argv[++i];
            else if ((p == L"--project" || p == L"--debug-build" || p == L"--build-and-debug") && i + 1 < argc) {
                init = argv[++i];
                debug = p != L"--project";
            } else if (p.size() && p[0] != L'-')
                init = p;
        }
        LocalFree(argv);
        Studio app(fs::absolute(base), fs::absolute(user));
        app.initial = init;
        app.autoDebug = debug;
        if (!lang.empty())
            english = (lang == L"en");
        WNDCLASSEXW cls{sizeof(cls)};
        cls.lpfnWndProc = mainProc;
        cls.hInstance = inst;
        cls.lpszClassName = appClass;
        cls.hCursor = LoadCursor(nullptr, IDC_ARROW);
        cls.hIcon = LoadIconW(inst, MAKEINTRESOURCEW(101));
        cls.hIconSm = cls.hIcon;
        RegisterClassExW(&cls);
        RECT work{};
        SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
        UINT dpi = GetDpiForSystem();
        int width = std::min<int>(work.right - work.left, MulDiv(1320, dpi, 96)),
            height = std::min<int>(work.bottom - work.top, MulDiv(842, dpi, 96));
        HWND h = CreateWindowExW(0, appClass, L"Fx Studio · Win32", WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
                                 work.left + (work.right - work.left - width) / 2,
                                 work.top + (work.bottom - work.top - height) / 2, width, height, nullptr, nullptr,
                                 inst, &app);
        if (h) {
            ShowWindow(h, show);
            UpdateWindow(h);
            MSG msg{};
            while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
                if ((msg.hwnd == h || IsChild(h, msg.hwnd)) && app.shortcuts(msg))
                    continue;
                if (msg.message == WM_KEYDOWN && msg.wParam == VK_TAB && GetFocus() != app.editor() &&
                    IsDialogMessageW(h, &msg))
                    continue;
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
            code = (int)msg.wParam;
        }
    } catch (const std::exception &e) {
        failure(nullptr, wide(e.what()));
    }
    Gdiplus::GdiplusShutdown(token);
    CoUninitialize();
    return code;
}
