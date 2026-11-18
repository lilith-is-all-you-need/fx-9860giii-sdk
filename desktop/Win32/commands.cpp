#include "studio.h"
#include <iomanip>

namespace {
constexpr wchar_t projects[] = L"CMake / Fx Studio\0CMakeLists.txt;*.fxide.json;*.fxdebug.json\0All files\0*.*\0";
W selectedText(HWND ed) {
    auto n = SendMessageW(ed, SCI_GETSELTEXT, 0, 0);
    if (n <= 1 || n > 8192)
        return {};
    Str s(n, 0);
    SendMessageW(ed, SCI_GETSELTEXT, 0, (LPARAM)s.data());
    s.resize(n - 1);
    return wide(s);
}
void item(HMENU m, int id, const W &title) { AppendMenuW(m, MF_STRING, id, title.c_str()); }
void sep(HMENU m) { AppendMenuW(m, MF_SEPARATOR, 0, nullptr); }
bool validLeaf(const W &n) {
    return !n.empty() && n != L"." && n != L".." && n.find_first_of(L":<>\"/\\|?*") == W::npos &&
           n.back() != L' ' && n.back() != L'.';
}
} // namespace
void Studio::menus() {
    HMENU fresh = CreateMenu();
    auto section = [&](const W &title) {
        auto sub = CreatePopupMenu();
        AppendMenuW(fresh, MF_POPUP, (UINT_PTR)sub, title.c_str());
        return sub;
    };
    HMENU f = section(tr(L"文件(&F)", L"&File"));
    item(f, New, tr(L"新建工程…\tCtrl+N", L"New project…\tCtrl+N"));
    item(f, Open, tr(L"打开工程…\tCtrl+O", L"Open project…\tCtrl+O"));
    item(f, Demo, tr(L"打开计数器示例", L"Open counter example"));
    item(f, ImportBuild, tr(L"载入已有调试包…", L"Open compiled debug bundle…"));
    sep(f);
    item(f, NewFile, tr(L"新建源文件…", L"New source file…"));
    item(f, Save, tr(L"保存\tCtrl+S", L"Save\tCtrl+S"));
    item(f, SaveAll, tr(L"全部保存\tCtrl+Shift+S", L"Save all\tCtrl+Shift+S"));
    item(f, CloseDoc, tr(L"关闭文件\tCtrl+W", L"Close file\tCtrl+W"));
    sep(f);
    item(f, Export, tr(L"导出已校验 G1A…", L"Export verified G1A…"));
    sep(f);
    item(f, Quit, tr(L"退出", L"Exit"));
    auto e = section(tr(L"编辑(&E)", L"&Edit"));
    for (auto [id, s] :
         std::initializer_list<std::pair<int, W>>{{Undo, tr(L"撤销\tCtrl+Z", L"Undo\tCtrl+Z")},
                                                  {Redo, tr(L"重做\tCtrl+Y", L"Redo\tCtrl+Y")},
                                                  {Cut, tr(L"剪切\tCtrl+X", L"Cut\tCtrl+X")},
                                                  {Copy, tr(L"复制\tCtrl+C", L"Copy\tCtrl+C")},
                                                  {Paste, tr(L"粘贴\tCtrl+V", L"Paste\tCtrl+V")},
                                                  {SelectAll, tr(L"全选\tCtrl+A", L"Select all\tCtrl+A")},
                                                  {Find, tr(L"查找…\tCtrl+F", L"Find…\tCtrl+F")},
                                                  {FindNext, tr(L"查找下一个\tF3", L"Find next\tF3")}})
        item(e, id, s);
    auto b = section(tr(L"构建(&B)", L"&Build"));
    item(b, Build, tr(L"构建工程\tCtrl+Shift+B", L"Build project\tCtrl+Shift+B"));
    item(b, Cancel, tr(L"取消构建", L"Cancel build"));
    item(b, Reveal, tr(L"打开产物目录", L"Open build folder"));
    auto d = section(tr(L"调试(&D)", L"&Debug"));
    for (auto [id, s] : std::initializer_list<std::pair<int, W>>{
             {Start, tr(L"启动 / 继续\tF5", L"Start / Continue\tF5")},
             {Pause, tr(L"暂停", L"Pause")},
             {Stop, tr(L"停止\tShift+F5", L"Stop\tShift+F5")},
             {Restart, tr(L"重新启动", L"Restart")},
             {Step, tr(L"逐语句\tF11", L"Step into\tF11")},
             {Next, tr(L"逐过程\tF10", L"Step over\tF10")},
             {Finish, tr(L"跳出函数\tShift+F11", L"Step out\tShift+F11")},
             {RunTo, tr(L"运行到光标\tCtrl+F10", L"Run to cursor\tCtrl+F10")},
             {StepI, tr(L"逐指令进入\tCtrl+Alt+F11", L"Step into instruction\tCtrl+Alt+F11")},
             {NextI, tr(L"逐指令经过\tCtrl+Alt+F10", L"Step over instruction\tCtrl+Alt+F10")},
             {Breakpoint, tr(L"切换行断点\tF9", L"Toggle breakpoint\tF9")},
             {Watchpoint, tr(L"添加数据断点…", L"Add watchpoint…")},
             {AddWatch, tr(L"添加监视…", L"Add watch…")}})
        item(d, id, s);
    auto t = section(tr(L"工具(&T)", L"&Tools"));
    item(t, Migrate, tr(L"迁移旧 fxlib 工程…", L"Migrate legacy fxlib project…"));
    item(t, Assets, tr(L"导入工程资源…", L"Import project asset…"));
    item(t, Profile, L"FX Profile Studio…");
    sep(t);
    item(t, Settings, tr(L"工具链设置…", L"Toolchain settings…"));
    auto lang = CreatePopupMenu();
    item(lang, LangZh, L"简体中文");
    item(lang, LangEn, L"English");
    CheckMenuRadioItem(lang, LangZh, LangEn, english ? LangEn : LangZh, MF_BYCOMMAND);
    AppendMenuW(t, MF_POPUP, (UINT_PTR)lang, L"Language / 语言");
    item(t, Classic, tr(L"打开经典 IDE", L"Open classic IDE"));
    auto h = section(tr(L"帮助(&H)", L"&Help"));
    item(h, Knowledge, tr(L"计算器资料库…", L"Calculator reference…"));
    item(h, Guide, tr(L"Win32 使用指南", L"Win32 getting started"));
    item(h, SdkGuide, tr(L"SDK 用户手册", L"SDK user guide"));
    item(h, DevManual, tr(L"开发与兼容手册", L"Development and compatibility guide"));
    item(h, AutomationGuide, tr(L"SDK 自动化接口", L"SDK automation reference"));
    auto old = menu;
    menu = fresh;
    SetMenu(win, fresh);
    if (old)
        DestroyMenu(old);
    DrawMenuBar(win);
}
bool Studio::allowed(int id) const {
    bool projectOpen = !project.empty(), docOpen = selected >= 0, free = !busy && !engineDown && !closing,
         inspect = free && live && paused;
    switch (id) {
    case New:
    case Open:
    case Demo:
    case ImportBuild:
    case WelcomeOpen:
    case WelcomeNew:
    case WelcomeDemo:
        return free;
    case Build:
    case Assets:
    case NewFile:
        return free && projectOpen && !imported && !live;
    case Save:
    case SaveAll:
        return free && docOpen && !imported && !live;
    case Export:
        return free && !g1a.empty();
    case Reveal:
        return projectOpen;
    case CloseDoc:
        return !busy && docOpen;
    case Start:
        return free && projectOpen && (!live || paused);
    case Stop:
        return !engineDown && !assetLock && (live || busy);
    case Cancel:
        return busy && !assetLock && (currentCmd == "build" || currentCmd == "start" || currentCmd == "restart");
    case Pause:
        return free && live && !paused;
    case Restart:
        return free && projectOpen;
    case Next:
    case Step:
    case StepI:
    case NextI:
    case Finish:
    case EditValue:
    case SelectFrame:
    case Inspect:
    case ReadMem:
    case WriteMem:
        return inspect;
    case RunTo:
        return inspect && docOpen;
    case Breakpoint:
        return free && docOpen && projectOpen && (!live || paused);
    case Watchpoint:
    case RemovePoint:
    case Condition:
    case EnablePoint:
    case AddWatch:
    case RemoveWatch:
        return free && projectOpen && (!live || paused);
    case Migrate:
    case Settings:
        return free && !live;
    case Cut:
    case Paste:
    case Undo:
    case Redo:
        return docOpen && !imported && !live && !busy;
    case Find:
    case FindNext:
    case Copy:
    case SelectAll:
        return docOpen;
    case ZoomScreen:
    case SaveScreen:
        return bitmap != nullptr;
    default:
        return true;
    }
}
void Studio::enable() {
    if (!win || !tree)
        return;
    for (auto &[id, h] : buttons)
        EnableWindow(h, id >= KeyFirst ? live && !engineDown && !closing : allowed(id));
    EnableWindow(mode, allowed(Build));
    for (auto &f : files)
        SendMessageW(f->editor, SCI_SETREADONLY, imported || live || busy, 0);
    if (menu)
        for (int i = 0; i < GetMenuItemCount(menu); ++i) {
            auto sub = GetSubMenu(menu, i);
            for (int j = 0; j < GetMenuItemCount(sub); ++j) {
                auto id = GetMenuItemID(sub, j);
                if (id > 0 && id != (UINT)-1)
                    EnableMenuItem(sub, id, MF_BYCOMMAND | (allowed(id) ? MF_ENABLED : MF_GRAYED));
            }
        }
    if (buttons.count(Start))
        SetWindowTextW(buttons[Start],
                       live && paused ? tr(L"继续", L"Continue").c_str() : tr(L"调试", L"Debug").c_str());
    InvalidateRect(win, nullptr, FALSE);
}
void Studio::act(int id) {
    if (!allowed(id))
        return;
    if (id == WelcomeOpen)
        id = Open;
    if (id == WelcomeNew)
        id = New;
    if (id == WelcomeDemo)
        id = Demo;
    int row = ListView_GetNextItem(grid, -1, LVNI_SELECTED);
    auto list = [&](const char *field) -> Json {
        return snapshot.contains(field) && snapshot[field].is_array() ? snapshot[field] : Json::array();
    };
    auto selectedRow = [&](const char *field) {
        auto arr = list(field);
        return row >= 0 && row < (int)arr.size() ? arr[row] : Json::object();
    };
    auto noSelection = [&] { note(tr(L"请先选择一行。", L"Select a row first.")); };
    auto point = [&]() -> Point * { return row >= 0 && row < (int)points.size() ? &points[row] : nullptr; };
    switch (id) {
    case New:
    case Demo:
        newProject(id == Demo);
        break;
    case Open:
    case ImportBuild: {
        auto p = chooseFile(win, tr(L"打开工程或调试包", L"Open project or debug bundle"),
                            id == Open ? projects : L"Fx Studio debug\0*.fxdebug.json\0");
        if (!p.empty())
            openProject(p);
        break;
    }
    case NewFile: {
        fs::path parent = project;
        auto found = nodes.find(TreeView_GetSelection(tree));
        if (found != nodes.end())
            parent = fs::is_directory(found->second) ? found->second : found->second.parent_path();
        std::vector<Field> f = {{tr(L"文件名", L"File name"), L"module.c"}};
        if (!askFields(win, tr(L"新建源文件", L"New source file"), f))
            break;
        if (!validLeaf(f[0].value))
            throw std::runtime_error("Invalid file name.");
        auto p = parent / f[0].value;
        HANDLE out = CreateFileW(p.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        checkWin(out != INVALID_HANDLE_VALUE, "Create source file");
        CloseHandle(out);
        reloadTree();
        openFile(p);
        note(tr(L"新源文件已创建。请在 CMakeLists.txt 中加入该文件。",
                L"Source file created. Add it to CMakeLists.txt."));
        break;
    }
    case Save:
        saveDoc(*doc());
        note(tr(L"已保存", L"Saved") + L" · " + doc()->path.filename().wstring());
        break;
    case SaveAll:
        saveAll();
        note(tr(L"文件已保存", L"Files saved"));
        break;
    case CloseDoc:
        closeDoc();
        break;
    case Quit:
        checkClose();
        break;
    case Undo:
        edit(SCI_UNDO);
        break;
    case Redo:
        edit(SCI_REDO);
        break;
    case Cut:
        edit(SCI_CUT);
        break;
    case Copy:
        edit(SCI_COPY);
        break;
    case Paste:
        edit(SCI_PASTE);
        break;
    case SelectAll:
        edit(SCI_SELECTALL);
        break;
    case Find:
    case FindNext: {
        if (id == Find || lastFind.empty()) {
            auto sel = selectedText(editor());
            std::vector<Field> f = {{tr(L"查找文本", L"Find text"), sel.empty() ? lastFind : sel}};
            if (!askFields(win, tr(L"查找", L"Find"), f))
                break;
            lastFind = f[0].value;
        }
        Str q = utf8(lastFind);
        if (q.empty())
            break;
        auto find = [&](LRESULT start, LRESULT end) {
            edit(SCI_SETTARGETSTART, start);
            edit(SCI_SETTARGETEND, end);
            edit(SCI_SETSEARCHFLAGS, 0);
            return edit(SCI_SEARCHINTARGET, q.size(), (LPARAM)q.c_str());
        };
        auto from = edit(SCI_GETSELECTIONEND);
        auto at = find(from, edit(SCI_GETLENGTH));
        if (at < 0)
            at = find(0, from);
        if (at >= 0) {
            edit(SCI_SETSEL, at, at + q.size());
            edit(SCI_SCROLLCARET);
            SetFocus(editor());
        } else
            note(tr(L"未找到匹配文本", L"No matching text"));
        break;
    }
    case Build:
    case Start:
    case Restart: {
        if (!live || id == Restart)
            saveAll();
        auto args = pointArgs();
        if (id == Build || (!live && !imported) || (id == Restart && !imported)) {
            Str cfg = id == Build && SendMessageW(mode, CB_GETCURSEL, 0, 0) == 1 ? "Release" : "Debug";
            if (id != Build)
                SendMessageW(mode, CB_SETCURSEL, 0, 0);
            args["configuration"] = cfg;
            g1a.clear();
            diagnostics = Json::array();
            setSheet(Logs);
            log(L"\r\n" + name + L"  /  " + wide(cfg));
            note(tr(L"正在构建", L"Building") + L" · " + wide(cfg));
        }
        request(id == Build ? "build" : id == Restart ? "restart" : "start", args);
        break;
    }
    case Cancel:
        engine.send({{"cmd", "cancel"}});
        note(tr(L"正在取消构建…", L"Cancelling build…"));
        break;
    case Stop:
        keysUp();
        if (busy) {
            engine.send({{"cmd", "cancel"}});
            ended = true;
        } else
            request("stop");
        break;
    case Pause:
        request("pause");
        break;
    case Step:
        request("step");
        break;
    case Next:
        request("next");
        break;
    case Finish:
        request("finish");
        break;
    case StepI:
        request("stepi");
        break;
    case NextI:
        request("nexti");
        break;
    case RunTo:
        request("runTo", {{"file", utf8(doc()->path.wstring())},
                          {"line", (int)edit(SCI_LINEFROMPOSITION, edit(SCI_GETCURRENTPOS)) + 1}});
        break;
    case Breakpoint:
        togglePoint((int)edit(SCI_LINEFROMPOSITION, edit(SCI_GETCURRENTPOS)) + 1);
        break;
    case Reveal:
        launchFile(win, g1a.empty() ? buildDir : g1a.parent_path());
        break;
    case Export: {
        auto p = chooseFile(win, tr(L"导出已校验的计算器插件", L"Export verified calculator add-in"),
                            L"Calculator add-in\0*.g1a\0", true, g1a.filename().wstring(), L"g1a");
        if (!p.empty())
            request("export", {{"path", utf8(p.wstring())}});
        break;
    }
    case AddWatch:
    case Watchpoint: {
        W expr = editor() ? selectedText(editor()) : W();
        std::vector<Field> f = {{tr(L"表达式", L"Expression"), expr}};
        if (id == Watchpoint)
            f.push_back({tr(L"触发条件", L"Access"), L"write", {L"write", L"read", L"access"}});
        if (!askFields(win, id == AddWatch ? tr(L"添加监视", L"Add watch") : tr(L"数据断点", L"Watchpoint"), f) ||
            f[0].value.empty())
            break;
        if (id == AddWatch) {
            if (std::find(watches.begin(), watches.end(), f[0].value) == watches.end())
                watches.push_back(f[0].value);
            setSheet(Watches);
            saveSession();
            if (paused)
                scheduleSnapshot(false);
        } else {
            Point p;
            p.id = nextId++;
            p.expression = f[0].value;
            p.access = f[1].value;
            points.push_back(p);
            setSheet(Points);
            updatePoints();
        }
        break;
    }
    case RemoveWatch:
        if (row >= 0 && row < (int)watches.size()) {
            watches.erase(watches.begin() + row);
            saveSession();
            table();
            if (paused)
                scheduleSnapshot(false);
        } else
            noSelection();
        break;
    case Condition:
    case RemovePoint:
    case EnablePoint: {
        auto *p = point();
        if (!p) {
            noSelection();
            break;
        }
        markerPosition();
        if (id == Condition) {
            if (!p->expression.empty()) {
                note(tr(L"条件用于源码行断点。", L"Conditions apply to source breakpoints."));
                break;
            }
            std::vector<Field> f = {
                {tr(L"命中条件（留空表示始终）", L"Break when (empty for always)"), p->condition}};
            if (!askFields(win, tr(L"断点条件", L"Breakpoint condition"), f))
                break;
            p->condition = f[0].value;
        } else if (id == EnablePoint)
            p->enabled = !p->enabled;
        else
            points.erase(points.begin() + row);
        updatePoints();
        break;
    }
    case EditValue:
    case Inspect: {
        W expr, current;
        Json v;
        if (sheet == Watches && row >= 0 && row < (int)watches.size()) {
            expr = watches[row];
            for (auto &it : list("watches"))
                if (val(it, "expression") == expr)
                    current = val(it, "value");
        }
        if (sheet == Locals) {
            v = selectedRow("locals");
            expr = val(v, "name");
            current = val(v, "value");
        }
        if (sheet == Registers) {
            v = selectedRow("registers");
            expr = val(v, "name");
            current = val(v, "value");
        }
        if (expr.empty()) {
            noSelection();
            break;
        }
        if (id == Inspect) {
            request("children", {{"expression", utf8(expr)}});
            break;
        }
        std::vector<Field> f = {{tr(L"新值或表达式", L"New value or expression"), current}};
        if (!askFields(win, expr, f) || f[0].value.empty())
            break;
        if (sheet == Registers)
            request("register", {{"number", v.at("number")}, {"value", utf8(f[0].value)}});
        else
            request("evaluate", {{"expression", utf8(L"(" + expr + L") = (" + f[0].value + L")")}});
        break;
    }
    case SelectFrame: {
        auto frame = selectedRow("stack");
        if (frame.contains("level"))
            request("frame", {{"level", frame["level"]}});
        else
            noSelection();
        break;
    }
    case ReadMem:
    case WriteMem: {
        std::vector<Field> f = {{tr(L"地址或表达式", L"Address or expression"), memAddress},
                                {id == ReadMem ? tr(L"长度（1–65536 字节）", L"Length (1–65536 bytes)")
                                               : tr(L"十六进制字节", L"Hexadecimal bytes"),
                                 id == ReadMem ? std::to_wstring(memCount) : L""}};
        if (!askFields(win, id == ReadMem ? tr(L"读取内存", L"Read memory") : tr(L"写入内存", L"Write memory"), f))
            break;
        memAddress = f[0].value;
        if (id == ReadMem) {
            size_t end = 0;
            int length = std::stoi(f[1].value, &end);
            if (end != f[1].value.size() || length < 1 || length > 65536)
                throw std::runtime_error("Length must be 1–65536.");
            memCount = length;
            request("read", {{"address", utf8(memAddress)}, {"count", length}});
        } else
            request("write", {{"address", utf8(memAddress)}, {"hex", utf8(f[1].value)}});
        break;
    }
    case Refresh:
        if (live && paused) {
            if (sheet == Memory)
                request("read", {{"address", utf8(memAddress)}, {"count", memCount}});
            else
                scheduleSnapshot(false);
        } else {
            reloadTree();
            refreshFiles();
        }
        break;
    case ZoomScreen:
        if (bitmap)
            screenWindow(win, &bitmap);
        break;
    case SaveScreen: {
        auto p = chooseFile(win, tr(L"保存原始屏幕", L"Save native-resolution screen"), L"PNG\0*.png\0", true,
                            L"fx-screen.png", L"png");
        if (!p.empty()) {
            savePng(*bitmap, p);
            note(tr(L"屏幕已保存", L"Screen saved") + L" · " + p.wstring());
        }
        break;
    }
    case Migrate: {
        auto src = chooseFolder(win, tr(L"选择旧 fxlib 工程", L"Choose legacy fxlib project"));
        if (src.empty())
            break;
        std::vector<Field> f = {
            {tr(L"新工程目录名", L"New project folder name"), src.filename().wstring() + L"-gint"}};
        if (!askFields(win, tr(L"迁移旧工程", L"Migrate legacy project"), f))
            break;
        if (!validLeaf(f[0].value))
            throw std::runtime_error("Invalid folder name.");
        auto parent = chooseFolder(win, tr(L"选择新工程的父目录", L"Select destination parent"));
        if (parent.empty() || !confirm())
            break;
        auto dest = parent / f[0].value;
        saveSession();
        setSheet(Logs);
        request("migrate", {{"destination", utf8(dest.wstring())},
                            {"args",
                             {"create", "--source", utf8(src.wstring()), "--output", utf8(dest.wstring()), "--name",
                              utf8(f[0].value)}}});
        break;
    }
    case Assets: {
        auto p = chooseFile(win, tr(L"选择要导入的资源", L"Choose project asset"), L"All resources\0*.*\0");
        if (p.empty())
            break;
        W symbol = p.stem().wstring();
        for (auto &c : symbol)
            if (!(c < 128 && (iswalnum(c) || c == L'_')))
                c = L'_';
        if (symbol.empty() || iswdigit(symbol[0]))
            symbol = L"asset_" + symbol;
        std::vector<Field> f = {
            {tr(L"资源格式", L"Resource format"), L"bitmap", {L"bitmap", L"image", L"binary", L"font"}},
            {tr(L"C 符号名", L"C symbol"), symbol},
            {tr(L"CMake 目标（单目标可留空）", L"CMake target (optional for a single target)"), L""}};
        if (!askFields(win, tr(L"导入工程资源", L"Import project asset"), f))
            break;
        Json args = {"import",         "--project", utf8(project.wstring()), "--input", utf8(p.wstring()), "--kind",
                     utf8(f[0].value), "--symbol",  utf8(f[1].value)};
        if (!f[2].value.empty()) {
            args.push_back("--target");
            args.push_back(utf8(f[2].value));
        }
        if (f[0].value == L"font") {
            std::vector<Field> fontFields = {
                {tr(L"字形网格（宽 x 高）", L"Glyph grid (width x height)"), L"8x8"},
                {tr(L"字符集", L"Character set"),
                 L"numeric",
                 {L"numeric", L"upper", L"alpha", L"alnum", L"print", L"ascii", L"256chars"}}};
            if (!askFields(win, tr(L"位图字体", L"Bitmap font"), fontFields))
                break;
            args.push_back("--font-grid");
            args.push_back(utf8(fontFields[0].value));
            args.push_back("--font-charset");
            args.push_back(utf8(fontFields[1].value));
        }
        saveAll();
        setSheet(Logs);
        request("asset", {{"args", args}});
        break;
    }
    case Profile:
        launchFile(win, root / L"ProfileStudio/ProfileStudio.exe");
        break;
    case Classic:
        launchFile(win, root / L"FxStudio.exe");
        break;
    case Knowledge:
        knowledgeWindow(win, root);
        break;
    case Guide:
        launchFile(win,root.parent_path()/L"开始使用.html");
        break;
    case SdkGuide:
        launchFile(win, root / (english ? L"docs/USER-GUIDE.en.html" : L"docs/USER-GUIDE.zh-CN.html"));
        break;
    case DevManual:
        launchFile(win, root / (english ? L"docs/loader/handbook/DEVELOPER-GUIDE.en.txt"
                                        : L"docs/loader/handbook/DEVELOPER-GUIDE.zh-CN.txt"));
        break;
    case AutomationGuide:
        detailWindow(win, L"SDK Automation", wide(readBytes(root / L"docs/AUTOMATION.md")));
        break;
    case Settings: {
        std::vector<Field> f = {
            {tr(L"原生 SDK 目录（留空使用随包版本）", L"Native SDK directory (empty for bundled)"),
             val(config, "sdk")},
            {tr(L"编译与调试缓存目录", L"Native build and debug cache"), val(config, "work")},
            {tr(L"模拟器程序", L"Emulator executable"), val(config, "emulator")},
            {L"GDB", val(config, "gdb")},
            {tr(L"新工程的 WSL 发行版", L"WSL distribution for new projects"),
             config.value("distro", Str()).empty() ? L"FxSDK-Dev-20261114" : val(config, "distro")}};
        if (!askFields(win, tr(L"工具链设置", L"Toolchain settings"), f))
            break;
        int i = 0;
        for (auto k : {"sdk", "work", "emulator", "gdb", "distro"})
            config[k] = utf8(f[i++].value);
        saveConfig();
        auto opts = config;
        opts["cmd"] = "settings";
        opts["applyDistro"] = true;
        engine.send(opts);
        break;
    }
    case LangZh:
    case LangEn:
        english = id == LangEn;
        fonts();
        theme();
        menus();
        tabNames();
        setSheet(sheet);
        saveConfig();
        note(tr(L"就绪", L"Ready"));
        enable();
        break;
    case ViewReport:
        if (row >= 0 && row < (int)diagnostics.size()) {
            auto &d = diagnostics[row];
            fs::path p = val(d, "file");
            if (fs::exists(p))
                openFile(p, d.value("line", 1));
            else
                note(p.wstring());
        }
        break;
    }
}
bool Studio::shortcuts(MSG &m) {
    if (m.message != WM_KEYDOWN && m.message != WM_SYSKEYDOWN)
        return false;
    bool ctrl = GetKeyState(VK_CONTROL) < 0, shift = GetKeyState(VK_SHIFT) < 0, alt = GetKeyState(VK_MENU) < 0;
    int id = 0;
    if (alt && !ctrl)
        return false;
    switch (m.wParam) {
    case 'N':
        if (ctrl)
            id = New;
        break;
    case 'O':
        if (ctrl)
            id = Open;
        break;
    case 'S':
        if (ctrl)
            id = shift ? SaveAll : Save;
        break;
    case 'W':
        if (ctrl)
            id = CloseDoc;
        break;
    case 'B':
        if (ctrl && shift)
            id = Build;
        break;
    case 'F':
        if (ctrl)
            id = Find;
        break;
    case VK_F3:
        id = FindNext;
        break;
    case VK_F5:
        id = shift ? Stop : Start;
        break;
    case VK_F9:
        id = Breakpoint;
        break;
    case VK_F10:
        id = ctrl ? (alt ? NextI : RunTo) : Next;
        break;
    case VK_F11:
        id = ctrl && alt ? StepI : shift ? Finish : Step;
        break;
    }
    if (!id)
        return false;
    try {
        act(id);
    } catch (const std::exception &e) {
        commandError(e);
    }
    return true;
}
void Studio::context(HWND src, POINT pt) {
    HMENU m = CreatePopupMenu();
    if (pt.x == -1)
        GetCursorPos(&pt);
    if (src == tree) {
        POINT p = pt;
        ScreenToClient(tree, &p);
        TVHITTESTINFO hit{};
        hit.pt = p;
        if (auto item = TreeView_HitTest(tree, &hit))
            TreeView_SelectItem(tree, item);
        item(m, NewFile, tr(L"新建源文件…", L"New source file…"));
        item(m, Refresh, tr(L"刷新", L"Refresh"));
    } else if (src == tabs) {
        POINT p = pt;
        ScreenToClient(tabs, &p);
        TCHITTESTINFO hit{};
        hit.pt = p;
        auto i = TabCtrl_HitTest(tabs, &hit);
        if (i >= 0)
            selectDoc(i);
        item(m, CloseDoc, tr(L"关闭文件", L"Close file"));
    } else if (src == editor()) {
        for (auto [id, s] :
             std::initializer_list<std::pair<int, W>>{{Copy, tr(L"复制", L"Copy")},
                                                      {Paste, tr(L"粘贴", L"Paste")},
                                                      {Find, tr(L"查找…", L"Find…")},
                                                      {Breakpoint, tr(L"切换断点", L"Toggle breakpoint")},
                                                      {AddWatch, tr(L"添加监视…", L"Add watch…")}})
            item(m, id, s);
    } else if (src == grid) {
        for (auto id : actions)
            item(m, id, windowText(buttons[id]));
    }
    if (GetMenuItemCount(m) > 0) {
        for (int i = 0; i < GetMenuItemCount(m); ++i) {
            auto id = GetMenuItemID(m, i);
            if (!allowed(id))
                EnableMenuItem(m, id, MF_BYCOMMAND | MF_GRAYED);
        }
        int selectedId = TrackPopupMenu(m, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0, win, nullptr);
        if (selectedId)
            act(selectedId);
    }
    DestroyMenu(m);
}
void Studio::setSheet(int index) {
    sheet = std::clamp(index, (int)Logs, (int)Problems);
    TabCtrl_SetCurSel(sheets, sheet);
    switch (sheet) {
    case Locals:
        actions = {Inspect, EditValue, Refresh};
        break;
    case Watches:
        actions = {AddWatch, RemoveWatch, Inspect, EditValue};
        break;
    case Stack:
        actions = {SelectFrame, Refresh};
        break;
    case Points:
        actions = {Watchpoint, EnablePoint, Condition, RemovePoint};
        break;
    case Registers:
        actions = {EditValue, Refresh};
        break;
    case Memory:
        actions = {ReadMem, WriteMem, Refresh};
        break;
    case Assembly:
        actions = {Refresh};
        break;
    default:
        actions.clear();
    }
    table();
    layout();
    enable();
}
void Studio::table(bool preserve) {
    if (!grid || sheet == Logs)
        return;
    int old = preserve ? ListView_GetNextItem(grid, -1, LVNI_SELECTED) : -1;
    SendMessageW(grid, WM_SETREDRAW, FALSE, 0);
    ListView_DeleteAllItems(grid);
    while (ListView_DeleteColumn(grid, 0)) {
    }
    std::vector<W> headers;
    std::vector<std::vector<W>> rows;
    auto nameHdr = tr(L"名称", L"Name"), valueHdr = tr(L"值", L"Value"), addrHdr = tr(L"地址", L"Address");
    auto get = [&](const char *key) {
        auto it = snapshot.find(key);
        return it != snapshot.end() && it->is_array() ? *it : Json::array();
    };
    switch (sheet) {
    case Locals:
        headers = {nameHdr, valueHdr, tr(L"类型", L"Type")};
        for (auto &v : get("locals"))
            rows.push_back({val(v, "name"), val(v, "value"), val(v, "type")});
        break;
    case Watches:
        headers = {tr(L"表达式", L"Expression"), valueHdr};
        for (auto &w : watches) {
            W value;
            for (auto &v : get("watches"))
                if (val(v, "expression") == w)
                    value = val(v, "value");
            rows.push_back({w, value});
        }
        break;
    case Stack:
        headers = {L"#", tr(L"函数", L"Function"), tr(L"源码位置", L"Source"), L"PC"};
        for (auto &v : get("stack"))
            rows.push_back({val(v, "level"), val(v, "function"),
                            fs::path(val(v, "file")).filename().wstring() + L"  " + val(v, "line"),
                            val(v, "address")});
        break;
    case Points:
        headers = {tr(L"位置 / 表达式", L"Location / expression"), tr(L"条件", L"Condition"),
                   tr(L"状态", L"Status")};
        for (auto &p : points)
            rows.push_back(
                {p.expression.empty() ? p.file.filename().wstring() + L":" + std::to_wstring(p.line) : p.expression,
                 p.expression.empty() ? p.condition : p.access,
                 !p.enabled         ? tr(L"已禁用", L"Disabled")
                 : p.status.empty() ? tr(L"待调试", L"Pending launch")
                                    : p.status});
        break;
    case Registers:
        headers = {nameHdr, valueHdr};
        for (auto &v : get("registers"))
            rows.push_back({val(v, "name"), val(v, "value")});
        break;
    case Assembly:
        headers = {addrHdr, tr(L"指令字节", L"Opcodes"), tr(L"指令", L"Instruction")};
        for (auto &v : get("disassembly"))
            rows.push_back({val(v, "address"), val(v, "opcodes"), val(v, "instruction")});
        break;
    case Memory: {
        headers = {tr(L"偏移", L"Offset"), tr(L"十六进制", L"Hex"), L"ASCII"};
        W hex = val(memory, "hex"), address = val(memory, "address");
        for (size_t i = 0; i < hex.size(); i += 32) {
            std::wostringstream off;
            off << address << L" + " << std::hex << std::uppercase << (i / 2);
            W bytes, ascii;
            for (size_t j = i; j < std::min(i + 32, hex.size()); j += 2) {
                W pair = hex.substr(j, 2);
                int v = std::stoi(pair, nullptr, 16);
                bytes += pair + L" ";
                ascii += v >= 32 && v < 127 ? (wchar_t)v : L'.';
            }
            rows.push_back({off.str(), bytes, ascii});
        }
        break;
    }
    case Problems:
        headers = {tr(L"位置", L"Location"), tr(L"级别", L"Severity"), tr(L"说明", L"Message")};
        for (auto &v : diagnostics)
            rows.push_back({fs::path(val(v, "file")).filename().wstring() + L":" + val(v, "line"),
                            val(v, "severity"), val(v, "message")});
        break;
    }
    RECT r{};
    GetClientRect(grid, &r);
    int width = std::max<int>(r.right - unit(12), unit(360));
    int used = 0;
    for (int i = 0; i < (int)headers.size(); ++i) {
        LVCOLUMNW c{};
        c.mask = LVCF_TEXT | LVCF_WIDTH;
        c.pszText = headers[i].data();
        c.cx = i == (int)headers.size() - 1 ? width - used : width / (int)headers.size();
        used += c.cx;
        ListView_InsertColumn(grid, i, &c);
    }
    for (int i = 0; i < (int)rows.size(); ++i) {
        auto &values = rows[i];
        LVITEMW item{};
        item.mask = LVIF_TEXT;
        item.iItem = i;
        item.pszText = values[0].data();
        ListView_InsertItem(grid, &item);
        for (int j = 1; j < (int)values.size(); ++j)
            ListView_SetItemText(grid, i, j, values[j].data());
    }
    if (old >= 0 && old < (int)rows.size())
        ListView_SetItemState(grid, old, LVIS_SELECTED | LVIS_FOCUSED, LVIS_SELECTED | LVIS_FOCUSED);
    SendMessageW(grid, WM_SETREDRAW, TRUE, 0);
    InvalidateRect(grid, nullptr, TRUE);
}
