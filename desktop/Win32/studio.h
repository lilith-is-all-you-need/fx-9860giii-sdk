#pragma once
#include "platform.h"

enum Action {
    Open = 101,
    New,
    Demo,
    Save,
    SaveAll,
    CloseDoc,
    Find,
    FindNext,
    NewFile,
    ImportBuild,
    Export,
    Reveal,
    Quit,
    Build = 130,
    Cancel,
    Start,
    Pause,
    Stop,
    Restart,
    Step,
    Next,
    Finish,
    StepI,
    NextI,
    RunTo,
    Breakpoint,
    Assets = 160,
    Migrate,
    Profile,
    Settings,
    LangZh,
    LangEn,
    Guide,
    Knowledge,
    Classic,
    ZoomScreen,
    SaveScreen,
    Undo,
    Redo,
    Cut,
    Copy,
    Paste,
    SelectAll,
    Refresh,
    AddWatch,
    RemoveWatch,
    EditValue,
    Inspect,
    SelectFrame,
    RemovePoint,
    EnablePoint,
    Condition,
    Watchpoint,
    ReadMem,
    WriteMem,
    ViewReport,
    DevManual,
    AutomationGuide,
    SdkGuide,
    Mode = 230,
    Tree,
    Docs,
    Inspector,
    Output,
    Grid,
    WelcomeOpen,
    WelcomeNew,
    WelcomeDemo,
    KeyFirst = 300
};
enum Sheet { Logs, Locals, Watches, Stack, Points, Registers, Memory, Assembly, Problems };
struct Doc {
    fs::path path;
    HWND editor{};
    Str original;
    bool bom{}, dirty{};
};
struct Point {
    int id{}, line{}, marker = -1;
    fs::path file;
    W condition, expression, access = L"write", status, number;
    bool enabled = true;
};
struct Area {
    int x, y, w, h;
};
struct Key {
    W label;
    Str code;
};
std::vector<Key> calculatorKeys();
void imageWindow(HWND owner, const fs::path &path, bool screen);
void screenWindow(HWND owner, std::shared_ptr<Gdiplus::Bitmap> *bitmap);
void knowledgeWindow(HWND owner, const fs::path &root);
void detailWindow(HWND owner, const W &title, const W &text);
std::shared_ptr<Gdiplus::Bitmap> loadImage(const fs::path &path, bool sharedScreen = false, UINT *frames = nullptr);
void savePng(Gdiplus::Bitmap &image, const fs::path &path);

class Studio {
  public:
    HWND variableView{};
    HWND win{}, tree{}, tabs{}, sheets{}, grid{}, output{}, mode{};
    fs::path root, data, initial, project, projectFile, buildDir, g1a, framebuffer;
    W name, status, lastFind, stopReason, pc, memAddress = L"$sp", logText;
    int memCount = 128, selected = -1, sheet = Logs, nextId = 1;
    int side = 182, right = 286, bottom = 206, splitDrag = 0;
    bool imported{}, busy{}, live{}, paused{}, engineDown{}, shutting{}, closing{}, snapshotWanted{},
        navigateNext{}, ended{}, creating{}, quietSettings{}, autoDebug{}, snapNavigation{}, assetLock{},
        hadError{};
    Json config = Json::object(), snapshot = Json::object(), memory, diagnostics = Json::array();
    Str currentCmd;
    fs::path execFile;
    int execLine{};
    std::vector<std::unique_ptr<Doc>> files;
    std::vector<Point> points;
    std::vector<W> watches;
    std::map<int, HWND> buttons;
    std::map<HTREEITEM, fs::path> nodes;
    std::vector<Key> keys = calculatorKeys();
    std::set<int> held;
    std::vector<int> actions;
    HFONT font{}, captionFont{}, bold{}, titleFont{}, bigFont{}, mono{};
    HIMAGELIST treeImages{};
    HMENU menu{};
    HMODULE sciDll{}, lexDll{};
    std::shared_ptr<Gdiplus::Bitmap> bitmap;
    FILETIME frameTime{};
    Area topArea{}, editorArea{}, leftArea{}, toolsArea{}, inspectArea{}, lcd{}, rightArea{}, statusArea{},
        welcome{};
    Bridge engine;
    Studio(const fs::path &sdk, const fs::path &userDir);
    ~Studio();
    void init(HWND h);
    void fonts();
    void layout();
    void theme();
    void menus();
    void paint(HDC dc);
    void buttonDraw(DRAWITEMSTRUCT &d);
    void enable();
    bool allowed(int id) const;
    void act(int id);
    void notify(NMHDR *event);
    void event(const Json &msg);
    void request(Str command, Json args = Json::object());
    void scheduleSnapshot(bool navigate);
    void idle();
    void note(const W &message);
    void log(const W &message);
    void setSheet(int index);
    void table(bool preserve = false);
    void tabNames();
    void refreshScreen();
    void keysUp();
    void key(int index, bool down);
    void saveConfig();
    void openProject(const fs::path &path);
    void newProject(bool demo);
    void opened(const Json &data);
    void reloadTree();
    void treeChildren(HTREEITEM parent, const fs::path &dir);
    void openFile(const fs::path &p, int line = 0);
    void selectDoc(int i);
    void saveDoc(Doc &doc);
    void saveAll();
    bool confirm(Doc *doc = nullptr);
    void closeDoc();
    void refreshFiles();
    void saveSession();
    void loadSession();
    void updatePoints();
    void markers(Doc &doc);
    void togglePoint(int line);
    void syncPoints();
    Json pointArgs();
    void markerPosition();
    Doc *doc() { return selected >= 0 && selected < (int)files.size() ? files[selected].get() : nullptr; }
    HWND editor() { return doc() ? doc()->editor : nullptr; }
    LRESULT edit(UINT msg, WPARAM wp = 0, LPARAM lp = 0) { return SendMessageW(editor(), msg, wp, lp); }
    void commandError(const std::exception &e);
    void shutdown();
    void checkClose();
    void inspectMembers(const Json &result);
    bool shortcuts(MSG &m);
    void context(HWND src, POINT where);
    void showError(const W &msg);
    HWND ctl(const wchar_t *cls, const W &text, DWORD flags, int id, DWORD ex = 0);
    HWND button(int id, const W &text);
    int unit(int v) const { return scaled(win, v); }
    void place(HWND h, int x, int y, int w, int height, bool show = true);
    int logical(int px) const { return MulDiv(px, 96, GetDpiForWindow(win)); }
};
