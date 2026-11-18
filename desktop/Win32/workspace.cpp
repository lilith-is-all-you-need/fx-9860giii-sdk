#include "studio.h"

namespace {
bool samePath(const fs::path &a, const fs::path &b) { return !_wcsicmp(a.c_str(), b.c_str()); }
bool ignored(const fs::path &path) {
    W n = path.filename().wstring();
    std::transform(n.begin(), n.end(), n.begin(), towlower);
    return n == L".git" || n == L".vs" || n == L".fxstudio" || n == L"bin" || n == L"obj" || n == L"__pycache__" ||
           n.rfind(L"build", 0) == 0;
}
bool reparse(const fs::path &p) {
    auto attr = GetFileAttributesW(p.c_str());
    return attr == INVALID_FILE_ATTRIBUTES || (attr & FILE_ATTRIBUTE_REPARSE_POINT) != 0;
}
bool textFile(const fs::path &p) {
    static const wchar_t *patterns =
        L"*.c;*.h;*.cpp;*.hpp;*.cc;*.cxx;*.hh;*.hxx;*.s;*.asm;*.inc;*.in;*.ipp;*.tpp;*.cmake;*.txt;*.json;*.md;*."
        L"rst;*.html;*.css;*.js;*.py;*.ps1;*.sh;*.bat;*.cmd;*.ini;*.cfg;*.conf;*.yaml;*.yml;*.toml;*.xml;*.csv;*."
        L"ld;*.lds;*.mak;*.mk;*.log;*.map;*.d;*.fxconv;Makefile;GNUmakefile;LICENSE;COPYING;README;fxconv-metadata;"
        L".gitignore;.gitattributes;.editorconfig";
    return PathMatchSpecW(p.filename().c_str(), patterns);
}
bool imageFile(const fs::path &p) {
    return PathMatchSpecW(p.filename().c_str(), L"*.png;*.bmp;*.jpg;*.jpeg;*.gif;*.tif;*.tiff;*.ico");
}
bool safeName(const W &s) {
    return !s.empty() && s != L"." && s != L".." && s.find_first_of(L"<>:\"/\\|?*") == W::npos &&
           s.back() != L'.' && s.back() != L' ' &&
           std::none_of(s.begin(), s.end(), [](wchar_t c) { return c < 32; });
}
Str loadText(const fs::path &p, bool &bom) {
    Str raw = readBytes(p, 4 * 1024 * 1024);
    bom = raw.rfind("\xEF\xBB\xBF", 0) == 0;
    if (bom)
        raw.erase(0, 3);
    (void)wide(raw);
    if (std::any_of(raw.begin(), raw.end(),
                    [](unsigned char c) { return c < 32 && c != 9 && c != 10 && c != 12 && c != 13; }))
        throw std::runtime_error("This file contains binary data.");
    return raw;
}
void styleEditor(HWND h, HMODULE lex, const fs::path &p) {
    auto sc = [&](UINT m, WPARAM a = 0, LPARAM b = 0) { return SendMessageW(h, m, a, b); };
    sc(SCI_SETCODEPAGE, SC_CP_UTF8);
    sc(SCI_STYLESETFONT, STYLE_DEFAULT, (LPARAM) "Consolas");
    sc(SCI_STYLESETSIZEFRACTIONAL, STYLE_DEFAULT, 1060);
    sc(SCI_STYLESETFORE, STYLE_DEFAULT, ink);
    sc(SCI_STYLESETBACK, STYLE_DEFAULT, paper);
    sc(SCI_STYLECLEARALL);
    sc(SCI_SETMARGINTYPEN, 0, SC_MARGIN_NUMBER);
    sc(SCI_SETMARGINWIDTHN, 0, scaled(h, 42));
    sc(SCI_STYLESETFORE, STYLE_LINENUMBER, RGB(105, 126, 126));
    sc(SCI_STYLESETBACK, STYLE_LINENUMBER, RGB(245, 249, 247));
    sc(SCI_SETMARGINTYPEN, 1, SC_MARGIN_SYMBOL);
    sc(SCI_SETMARGINWIDTHN, 1, scaled(h, 16));
    sc(SCI_SETMARGINMASKN, 1, 7);
    sc(SCI_SETMARGINSENSITIVEN, 1, TRUE);
    sc(SCI_MARKERDEFINE, 0, SC_MARK_CIRCLE);
    sc(SCI_MARKERSETBACK, 0, RGB(204, 72, 63));
    sc(SCI_MARKERSETFORE, 0, RGB(153, 54, 45));
    sc(SCI_MARKERDEFINE, 1, SC_MARK_CIRCLE);
    sc(SCI_MARKERSETBACK, 1, RGB(203, 211, 208));
    sc(SCI_MARKERDEFINE, 2, SC_MARK_SHORTARROW);
    sc(SCI_MARKERSETBACK, 2, accent);
    sc(SCI_MARKERSETFORE, 2, accent);
    sc(SCI_MARKERDEFINE, 3, SC_MARK_BACKGROUND);
    sc(SCI_MARKERSETBACK, 3, RGB(218, 245, 229));
    sc(SCI_SETCARETFORE, accent);
    sc(SCI_SETCARETLINEVISIBLE, TRUE);
    sc(SCI_SETCARETLINEBACK, RGB(244, 248, 244));
    sc(SCI_SETSELBACK, TRUE, RGB(189, 227, 217));
    sc(SCI_SETUSETABS, FALSE);
    sc(SCI_SETTABWIDTH, 4);
    sc(SCI_SETINDENT, 4);
    sc(SCI_SETINDENTATIONGUIDES, SC_IV_LOOKBOTH);
    sc(SCI_STYLESETFORE, STYLE_INDENTGUIDE, RGB(217, 225, 220));
    sc(SCI_SETEXTRAASCENT, scaled(h, 2));
    sc(SCI_SETEXTRADESCENT, scaled(h, 1));
    sc(SCI_SETSCROLLWIDTHTRACKING, TRUE);
    sc(SCI_SETSCROLLWIDTH, 1);
    W name = p.filename().wstring();
    const char *lexer = nullptr;
    if (PathMatchSpecW(name.c_str(), L"*.c;*.cpp;*.h;*.hpp;*.cxx;*.cc;*.hh;*.hxx;*.ipp;*.tpp;*.inc"))
        lexer = "cpp";
    else if (PathMatchSpecW(name.c_str(), L"CMakeLists.txt;*.cmake"))
        lexer = "cmake";
    else if (PathMatchSpecW(name.c_str(), L"*.json"))
        lexer = "json";
    else if (PathMatchSpecW(name.c_str(), L"*.py"))
        lexer = "python";
    else if (PathMatchSpecW(name.c_str(), L"*.s;*.asm"))
        lexer = "asm";
    if (lexer) {
        using CreateLexerFn = void *(__stdcall *)(const char *);
        auto create = reinterpret_cast<CreateLexerFn>(GetProcAddress(lex, "CreateLexer"));
        if (!create)
            throw std::runtime_error("Lexilla CreateLexer unavailable");
        sc(SCI_SETILEXER, 0, (LPARAM)create(lexer));
        if (Str(lexer) == "cpp") {
            sc(SCI_SETKEYWORDS, 0,
               (LPARAM) "alignas auto bool break case catch char class const constexpr consteval continue default "
                        "delete do double else enum explicit extern false float for friend goto if inline int long "
                        "namespace new noexcept nullptr operator private protected public register restrict return "
                        "short signed sizeof static static_assert struct switch template this throw true try "
                        "typedef typename union unsigned using virtual void volatile while _Bool _Static_assert");
            for (int style : {SCE_C_COMMENT, SCE_C_COMMENTLINE, SCE_C_COMMENTDOC, SCE_C_COMMENTLINEDOC}) {
                sc(SCI_STYLESETFORE, style, RGB(85, 118, 97));
                sc(SCI_STYLESETITALIC, style, TRUE);
            }
            sc(SCI_STYLESETFORE, SCE_C_WORD, RGB(32, 75, 139));
            sc(SCI_STYLESETBOLD, SCE_C_WORD, TRUE);
            sc(SCI_STYLESETFORE, SCE_C_PREPROCESSOR, RGB(111, 72, 137));
            for (int style : {SCE_C_CHARACTER, SCE_C_STRING, SCE_C_STRINGRAW, SCE_C_VERBATIM})
                sc(SCI_STYLESETFORE, style, RGB(151, 82, 38));
            sc(SCI_STYLESETFORE, SCE_C_NUMBER, RGB(142, 66, 106));
            sc(SCI_STYLESETFORE, SCE_C_OPERATOR, RGB(55, 99, 99));
        } else {
            for (int style : {1, 2, 3, 4, 5, 6, 7, 8})
                sc(SCI_STYLESETFORE, style, style % 2 ? RGB(55, 113, 91) : RGB(124, 80, 113));
        }
    }
}
} // namespace
void Studio::openProject(const fs::path &path) {
    if (busy || !confirm())
        return;
    saveSession();
    request("open", {{"path", utf8(fs::absolute(path).wstring())}});
}
void Studio::newProject(bool demo) {
    W folder;
    fs::path parent, base;
    if (demo) {
        parent = data / L"Projects";
        folder = L"Counter-" + std::to_wstring(std::chrono::system_clock::now().time_since_epoch().count());
        base = root / L"examples/counter-cpp";
    } else {
        std::vector<Field> fields = {{tr(L"工程名称", L"Project name"), L"MyAddin"},
                                     {tr(L"模板", L"Template"), L"C++", {L"C++", L"C", L"C · guarded"}}};
        if (!askFields(win, tr(L"新建工程", L"New project"), fields))
            return;
        folder = fields[0].value;
        if (!safeName(folder))
            throw std::runtime_error("Invalid project folder name.");
        parent = chooseFolder(win, tr(L"选择工程的父目录", L"Select the parent directory"));
        if (parent.empty())
            return;
        base = fields[1].value == L"C++" ? root / L"examples/counter-cpp"
               : fields[1].value == L"C" ? root / L"examples/counter-c"
                                         : root / L"scaffolds/guarded-c";
    }
    if (!confirm())
        return;
    auto dest = parent / folder;
    fs::create_directories(parent);
    if (!fs::create_directory(dest))
        throw std::runtime_error(utf8(tr(L"同名目录已经存在，请换一个工程名。",
                                         L"The destination already exists. Choose another project name.")));
    try {
        for (fs::recursive_directory_iterator i(base), end; i != end; ++i) {
            auto &e = *i;
            if (reparse(e.path()) || (e.is_directory() && ignored(e.path()))) {
                i.disable_recursion_pending();
                continue;
            }
            if (e.is_regular_file() && e.path().filename() != L"project.fxide.json") {
                auto target = dest / e.path().lexically_relative(base);
                fs::create_directories(target.parent_path());
                fs::copy_file(e.path(), target);
            }
        }
    } catch (...) {
        std::error_code ec;
        fs::remove_all(dest, ec);
        throw;
    }
    saveSession();
    request("open", {{"path", utf8(dest.wstring())}});
}
void Studio::opened(const Json &d) {
    selected = -1;
    for (auto &f : files)
        DestroyWindow(f->editor);
    files.clear();
    TabCtrl_DeleteAllItems(tabs);
    name = val(d, "name");
    project = val(d, "directory");
    projectFile = val(d, "path");
    buildDir = val(d, "build");
    imported = d.value("imported", false);
    g1a.clear();
    framebuffer.clear();
    bitmap.reset();
    execFile.clear();
    execLine = 0;
    points.clear();
    watches.clear();
    memory = nullptr;
    snapshot = Json::object();
    diagnostics = Json::array();
    live = paused = false;
    snapshotWanted = false;
    loadSession();
    reloadTree();
    config["last"] = utf8(projectFile.wstring());
    saveConfig();
    for (auto main : {L"src/main.cpp", L"src/main.c", L"main.cpp", L"main.c", L"CMakeLists.txt"})
        if (fs::is_regular_file(project / main)) {
            openFile(project / main);
            break;
        }
    note(imported ? tr(L"已载入调试包 · 源码只读", L"Debug bundle loaded · read-only source")
                  : tr(L"工程已打开", L"Project opened") + L" · " + name);
    setSheet(Logs);
    layout();
    enable();
}
void Studio::reloadTree() {
    TreeView_DeleteAllItems(tree);
    nodes.clear();
    if (project.empty())
        return;
    TVINSERTSTRUCTW v{};
    v.hParent = TVI_ROOT;
    v.hInsertAfter = TVI_LAST;
    v.item.mask = TVIF_TEXT | TVIF_CHILDREN | TVIF_STATE | TVIF_IMAGE | TVIF_SELECTEDIMAGE;
    v.item.state = v.item.stateMask = TVIS_BOLD;
    v.item.pszText = name.data();
    v.item.cChildren = 1;
    SHFILEINFOW fi{};
    SHGetFileInfoW(L"folder", FILE_ATTRIBUTE_DIRECTORY, &fi, sizeof(fi),
                   SHGFI_USEFILEATTRIBUTES | SHGFI_SYSICONINDEX | SHGFI_SMALLICON);
    v.item.iImage = v.item.iSelectedImage = fi.iIcon;
    auto item = TreeView_InsertItem(tree, &v);
    nodes[item] = project;
    TreeView_Expand(tree, item, TVE_EXPAND);
    auto ch = TreeView_GetChild(tree, item);
    while (ch) {
        if (nodes[ch].filename() == L"src") {
            TreeView_Expand(tree, ch, TVE_EXPAND);
            break;
        }
        ch = TreeView_GetNextSibling(tree, ch);
    }
}
void Studio::treeChildren(HTREEITEM parent, const fs::path &dir) {
    if (TreeView_GetChild(tree, parent))
        return;
    std::vector<fs::directory_entry> entries;
    for (auto &e : fs::directory_iterator(dir, fs::directory_options::skip_permission_denied)) {
        if (!reparse(e.path()) && !(e.is_directory() && ignored(e.path())))
            entries.push_back(e);
    }
    std::sort(entries.begin(), entries.end(), [](const auto &a, const auto &b) {
        return a.is_directory() != b.is_directory()
                   ? a.is_directory()
                   : _wcsicmp(a.path().filename().c_str(), b.path().filename().c_str()) < 0;
    });
    for (auto &e : entries) {
        W n = e.path().filename().wstring();
        TVINSERTSTRUCTW v{};
        v.hParent = parent;
        v.hInsertAfter = TVI_LAST;
        v.item.mask = TVIF_TEXT | TVIF_CHILDREN | TVIF_IMAGE | TVIF_SELECTEDIMAGE;
        v.item.pszText = n.data();
        v.item.cChildren = e.is_directory() ? 1 : 0;
        SHFILEINFOW info{};
        SHGetFileInfoW(n.c_str(), e.is_directory() ? FILE_ATTRIBUTE_DIRECTORY : FILE_ATTRIBUTE_NORMAL, &info,
                       sizeof(info), SHGFI_USEFILEATTRIBUTES | SHGFI_SYSICONINDEX | SHGFI_SMALLICON);
        v.item.iImage = v.item.iSelectedImage = info.iIcon;
        nodes[TreeView_InsertItem(tree, &v)] = e.path();
    }
}
void Studio::openFile(const fs::path &path, int line) {
    fs::path p = fs::absolute(path).lexically_normal();
    if (!fs::is_regular_file(p))
        return;
    if (!textFile(p)) {
        if (imageFile(p))
            imageWindow(win, p, false);
        else
            detailWindow(win, p.filename().wstring(),
                         p.wstring() + L"\r\n\r\n" + std::to_wstring(fs::file_size(p)) + L" bytes");
        return;
    }
    auto i = std::find_if(files.begin(), files.end(), [&](const auto &f) { return samePath(p, f->path); });
    if (i != files.end())
        selectDoc(static_cast<int>(i - files.begin()));
    else {
        auto f = std::make_unique<Doc>();
        f->path = p;
        f->original = loadText(p, f->bom);
        f->editor = ctl(L"Scintilla", L"", WS_TABSTOP | WS_CLIPSIBLINGS, 0);
        styleEditor(f->editor, lexDll, p);
        SendMessageW(f->editor, SCI_SETTEXT, 0, (LPARAM)f->original.c_str());
        SendMessageW(f->editor, SCI_SETEOLMODE, f->original.find("\r\n") != Str::npos ? SC_EOL_CRLF : SC_EOL_LF, 0);
        SendMessageW(f->editor, SCI_EMPTYUNDOBUFFER, 0, 0);
        SendMessageW(f->editor, SCI_SETSAVEPOINT, 0, 0);
        SendMessageW(f->editor, SCI_SETREADONLY, imported || live || busy && assetLock, 0);
        W tab = p.filename().wstring();
        TCITEMW t{};
        t.mask = TCIF_TEXT;
        t.pszText = tab.data();
        TabCtrl_InsertItem(tabs, static_cast<int>(files.size()), &t);
        markers(*f);
        files.push_back(std::move(f));
        selectDoc(static_cast<int>(files.size()) - 1);
    }
    if (line > 0) {
        edit(SCI_ENSUREVISIBLEENFORCEPOLICY, line - 1);
        edit(SCI_GOTOLINE, line - 1);
        edit(SCI_SCROLLCARET);
    }
}
void Studio::selectDoc(int i) {
    if (i < 0 || i >= (int)files.size())
        return;
    selected = i;
    TabCtrl_SetCurSel(tabs, i);
    layout();
    SetFocus(editor());
    enable();
}
void Studio::tabNames() {
    if (!sheets)
        return;
    TabCtrl_DeleteAllItems(sheets);
    for (auto s : {tr(L"输出", L"Output"), tr(L"局部变量", L"Locals"), tr(L"监视", L"Watches"),
                   tr(L"调用栈", L"Stack"), tr(L"断点", L"Breakpoints"), tr(L"寄存器", L"Registers"),
                   tr(L"内存", L"Memory"), tr(L"反汇编", L"Assembly"), tr(L"诊断", L"Problems")}) {
        TCITEMW t{};
        t.mask = TCIF_TEXT;
        t.pszText = s.data();
        TabCtrl_InsertItem(sheets, TabCtrl_GetItemCount(sheets), &t);
    }
    TabCtrl_SetCurSel(sheets, sheet);
    for (int i = 0; i < (int)files.size(); ++i) {
        W text = files[i]->path.filename().wstring();
        if (files[i]->dirty)
            text += L"  •";
        TCITEMW t{};
        t.mask = TCIF_TEXT;
        t.pszText = text.data();
        TabCtrl_SetItem(tabs, i, &t);
    }
}
void Studio::saveDoc(Doc &d) {
    if (!d.dirty)
        return;
    if (imported)
        throw std::runtime_error("Imported debug sources are read-only.");
    if (!fs::exists(d.path) ||
        readBytes(d.path, 16 * 1024 * 1024) != (d.bom ? Str("\xef\xbb\xbf") : Str()) + d.original)
        throw std::runtime_error(
            utf8(tr(L"磁盘文件已被其他程序修改。保留了编辑器内容，请先核对文件。",
                    L"The file changed on disk. Your buffer is retained; review the external changes.")) +
            " " + utf8(d.path.wstring()));
    auto n = SendMessageW(d.editor, SCI_GETLENGTH, 0, 0);
    Str buf(static_cast<size_t>(n) + 1, 0);
    SendMessageW(d.editor, SCI_GETTEXT, buf.size(), (LPARAM)buf.data());
    buf.resize((size_t)n);
    atomicWrite(d.path, (d.bom ? Str("\xef\xbb\xbf") : Str()) + buf);
    d.original = std::move(buf);
    d.dirty = false;
    SendMessageW(d.editor, SCI_SETSAVEPOINT, 0, 0);
    tabNames();
    saveSession();
}
void Studio::saveAll() {
    for (auto &d : files)
        saveDoc(*d);
}
bool Studio::confirm(Doc *one) {
    bool dirty = one ? one->dirty : std::any_of(files.begin(), files.end(), [](auto &f) { return f->dirty; });
    if (!dirty)
        return true;
    int choice = MessageBoxW(win, tr(L"保存修改后继续？", L"Save changes before continuing?").c_str(), L"Fx Studio",
                             MB_YESNOCANCEL | MB_ICONQUESTION);
    if (choice == IDCANCEL)
        return false;
    if (choice == IDYES) {
        if (one)
            saveDoc(*one);
        else
            saveAll();
    }
    return true;
}
void Studio::closeDoc() {
    if (!doc() || !confirm(doc()))
        return;
    int i = selected;
    markerPosition();
    for (auto &b : points)
        if (samePath(b.file, doc()->path))
            b.marker = -1;
    selected = -1;
    DestroyWindow(files[i]->editor);
    files.erase(files.begin() + i);
    TabCtrl_DeleteItem(tabs, i);
    if (!files.empty())
        selectDoc(std::min(i, (int)files.size() - 1));
    else {
        layout();
        enable();
    }
    saveSession();
}
void Studio::refreshFiles() {
    for (auto &d : files) {
        if (d->dirty || !fs::exists(d->path))
            continue;
        bool bom = false;
        auto text = loadText(d->path, bom);
        if (text == d->original && bom == d->bom)
            continue;
        auto pos = SendMessageW(d->editor, SCI_GETCURRENTPOS, 0, 0);
        SendMessageW(d->editor, SCI_SETREADONLY, FALSE, 0);
        SendMessageW(d->editor, SCI_SETTEXT, 0, (LPARAM)text.c_str());
        d->original = std::move(text);
        d->bom = bom;
        SendMessageW(d->editor, SCI_EMPTYUNDOBUFFER, 0, 0);
        SendMessageW(d->editor, SCI_SETSAVEPOINT, 0, 0);
        SendMessageW(d->editor, SCI_GOTOPOS, std::min<size_t>(pos, d->original.size()), 0);
        SendMessageW(d->editor, SCI_SETREADONLY, imported || live, 0);
        d->dirty = false;
        markers(*d);
    }
    tabNames();
}
void Studio::saveSession() {
    if (project.empty() || imported)
        return;
    markerPosition();
    Json bs = Json::array(), ws = Json::array();
    for (auto &p : points) {
        bs.push_back({{"File", p.file.empty() ? "." : utf8(fs::relative(p.file, project).wstring())},
                      {"Line", p.line},
                      {"Condition", utf8(p.condition)},
                      {"Expression", utf8(p.expression)},
                      {"Access", utf8(p.access)},
                      {"Enabled", p.enabled}});
    }
    for (auto &w : watches)
        ws.push_back(utf8(w));
    atomicWrite(project / L".fxstudio/session.json", Json{{"Breakpoints", bs}, {"Watches", ws}}.dump(2));
}
void Studio::loadSession() {
    if (imported)
        return;
    auto path = project / L".fxstudio/session.json";
    if (!fs::exists(path))
        return;
    auto j = Json::parse(readBytes(path), nullptr, false);
    if (!j.is_object())
        return;
    for (auto &b : j.value("Breakpoints", Json::array())) {
        Point p;
        p.id = nextId++;
        p.line = b.value("Line", 0);
        p.expression = val(b, "Expression");
        if (p.expression.empty())
            p.file = fs::absolute(project / val(b, "File")).lexically_normal();
        p.condition = val(b, "Condition");
        p.enabled = b.value("Enabled", true);
        p.access = val(b, "Access");
        if (p.access.empty())
            p.access = L"write";
        points.push_back(p);
    }
    for (auto &w : j.value("Watches", Json::array()))
        if (w.is_string())
            watches.push_back(wide(w.get<Str>()));
}
void Studio::markerPosition() {
    for (auto &p : points)
        if (p.marker >= 0)
            for (auto &f : files)
                if (samePath(p.file, f->path)) {
                    auto n = SendMessageW(f->editor, SCI_MARKERLINEFROMHANDLE, p.marker, 0);
                    if (n >= 0)
                        p.line = (int)n + 1;
                    break;
                }
}
void Studio::markers(Doc &d) {
    for (int id = 0; id <= 3; ++id)
        SendMessageW(d.editor, SCI_MARKERDELETEALL, id, 0);
    for (auto &p : points)
        if (samePath(p.file, d.path) && p.expression.empty())
            p.marker = (int)SendMessageW(d.editor, SCI_MARKERADD, p.line - 1, p.enabled ? 0 : 1);
    if (execLine > 0 && samePath(execFile, d.path)) {
        SendMessageW(d.editor, SCI_MARKERADD, execLine - 1, 2);
        SendMessageW(d.editor, SCI_MARKERADD, execLine - 1, 3);
    }
}
Json Studio::pointArgs() {
    markerPosition();
    Json a = Json::array();
    for (auto &p : points)
        a.push_back({{"id", p.id},
                     {"file", utf8(p.file.wstring())},
                     {"line", p.line},
                     {"expression", utf8(p.expression)},
                     {"condition", utf8(p.condition)},
                     {"access", utf8(p.access)},
                     {"enabled", p.enabled}});
    return {{"points", a}};
}
void Studio::syncPoints() {
    if (live && paused)
        request("points", pointArgs());
}
void Studio::updatePoints() {
    for (auto &d : files)
        markers(*d);
    saveSession();
    if (sheet == Points)
        table(true);
    syncPoints();
}
void Studio::togglePoint(int line) {
    if (!doc() || busy || live && !paused)
        return;
    markerPosition();
    auto it = std::find_if(points.begin(), points.end(), [&](const Point &p) {
        return p.line == line && samePath(p.file, doc()->path) && p.expression.empty();
    });
    if (it == points.end()) {
        Point p;
        p.id = nextId++;
        p.file = doc()->path;
        p.line = line;
        points.push_back(p);
    } else
        points.erase(it);
    updatePoints();
}
void Studio::notify(NMHDR *n) {
    if (!n)
        return;
    if (n->hwndFrom == tree) {
        if (n->code == TVN_ITEMEXPANDINGW) {
            auto t = reinterpret_cast<NMTREEVIEWW *>(n);
            auto it = nodes.find(t->itemNew.hItem);
            if (t->action == TVE_EXPAND && it != nodes.end())
                treeChildren(it->first, it->second);
        }
        if (n->code == NM_DBLCLK ||
            (n->code == TVN_KEYDOWN && reinterpret_cast<NMTVKEYDOWN *>(n)->wVKey == VK_RETURN)) {
            auto it = nodes.find(TreeView_GetSelection(tree));
            if (it != nodes.end() && fs::is_regular_file(it->second))
                openFile(it->second);
        }
    } else if (n->hwndFrom == tabs && n->code == TCN_SELCHANGE) {
        selectDoc(TabCtrl_GetCurSel(tabs));
    } else if (n->hwndFrom == sheets && n->code == TCN_SELCHANGE) {
        setSheet(TabCtrl_GetCurSel(sheets));
    } else if (n->hwndFrom == grid) {
        if (n->code == NM_DBLCLK ||
            (n->code == LVN_KEYDOWN && reinterpret_cast<NMLVKEYDOWN *>(n)->wVKey == VK_RETURN)) {
            if (sheet == Locals || sheet == Watches)
                act(Inspect);
            else if (sheet == Stack)
                act(SelectFrame);
            else if (sheet == Registers)
                act(EditValue);
            else if (sheet == Points) {
                int i = ListView_GetNextItem(grid, -1, LVNI_SELECTED);
                if (i >= 0 && i < (int)points.size() && !points[i].file.empty())
                    openFile(points[i].file, points[i].line);
            } else if (sheet == Problems)
                act(ViewReport);
        }
    } else {
        auto it = std::find_if(files.begin(), files.end(), [&](const auto &f) { return f->editor == n->hwndFrom; });
        if (it == files.end())
            return;
        auto &d = **it;
        auto *sn = reinterpret_cast<SCNotification *>(n);
        if (n->code == SCN_SAVEPOINTLEFT || n->code == SCN_SAVEPOINTREACHED) {
            d.dirty = n->code == SCN_SAVEPOINTLEFT;
            if (d.dirty)
                g1a.clear();
            tabNames();
            enable();
        } else if (n->code == SCN_MARGINCLICK && sn->margin == 1) {
            togglePoint((int)SendMessageW(d.editor, SCI_LINEFROMPOSITION, sn->position, 0) + 1);
        } else if (n->code == SCN_UPDATEUI && (sn->updated & SC_UPDATE_SELECTION)) {
            RECT r{unit(statusArea.w - 292), unit(statusArea.y), unit(statusArea.w),
                   unit(statusArea.y + statusArea.h)};
            InvalidateRect(win, &r, FALSE);
        }
    }
}
