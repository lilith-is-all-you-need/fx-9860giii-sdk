#include "platform.h"

HINSTANCE instance{};
bool english{};
void checkWin(BOOL result, const char *action) {
    if (!result)
        throw std::system_error(static_cast<int>(GetLastError()), std::system_category(), action);
}
W wide(const Str &s) {
    if (s.empty())
        return {};
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()), nullptr, 0);
    checkWin(n, "UTF-8");
    W out(n, 0);
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()), out.data(), n);
    return out;
}
Str utf8(const W &s) {
    if (s.empty())
        return {};
    int n = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()), nullptr, 0,
                                nullptr, nullptr);
    checkWin(n, "Unicode");
    Str out(n, 0);
    WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, s.data(), static_cast<int>(s.size()), out.data(), n, nullptr,
                        nullptr);
    return out;
}
W val(const Json &o, const char *k) {
    if (!o.is_object() || !o.contains(k) || o[k].is_null())
        return {};
    return o[k].is_string() ? wide(o[k].get<Str>()) : wide(o[k].dump());
}
Str readBytes(const fs::path &file, size_t limit) {
    auto n = fs::file_size(file);
    if (n > limit)
        throw std::runtime_error(
            utf8(tr(L"文件超过此视图的大小限制。", L"File exceeds the size limit for this view.")));
    std::ifstream in(file, std::ios::binary);
    Str bytes(static_cast<size_t>(n), '\0');
    if (!in || (n && !in.read(bytes.data(), static_cast<std::streamsize>(n))))
        throw std::runtime_error("Cannot read: " + utf8(file.wstring()));
    return bytes;
}
void atomicWrite(const fs::path &p, const Str &bytes) {
    fs::create_directories(p.parent_path());
    GUID guid{};
    CoCreateGuid(&guid);
    wchar_t suffix[48]{};
    StringFromGUID2(guid, suffix, 48);
    auto tmp = p.parent_path() / (L".fxstudio-" + W(suffix) + L".tmp");
    try {
        std::ofstream out(tmp, std::ios::binary | std::ios::trunc);
        out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
        out.close();
        if (!out)
            throw std::runtime_error("Write failed: " + utf8(p.wstring()));
        checkWin(MoveFileExW(tmp.c_str(), p.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH),
                 "Replace file");
    } catch (...) {
        std::error_code ec;
        fs::remove(tmp, ec);
        throw;
    }
}
W windowText(HWND w) {
    W text(GetWindowTextLengthW(w) + 1, 0);
    int n = GetWindowTextW(w, text.data(), static_cast<int>(text.size()));
    text.resize(n);
    return text;
}
void launchFile(HWND owner, const fs::path &p) {
    if (!fs::exists(p))
        throw std::runtime_error("Missing: " + utf8(p.wstring()));
    if (reinterpret_cast<INT_PTR>(
            ShellExecuteW(owner, L"open", p.c_str(), nullptr, p.parent_path().c_str(), SW_SHOWNORMAL)) <= 32)
        throw std::runtime_error("Could not open: " + utf8(p.wstring()));
}
void failure(HWND w, const W &s) { MessageBoxW(w, s.c_str(), L"Fx Studio", MB_OK | MB_ICONWARNING); }
int scaled(HWND w, int n) { return MulDiv(n, GetDpiForWindow(w), 96); }
HFONT makeFont(HWND w, int h, int weight, const wchar_t *face) {
    if (!english && wcscmp(face, L"Segoe UI") == 0)
        face = L"Microsoft YaHei UI";
    return CreateFontW(-scaled(w, h), 0, 0, 0, weight, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                       CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, face);
}
void fill(HDC dc, RECT r, COLORREF c) {
    SetDCBrushColor(dc, c);
    FillRect(dc, &r, (HBRUSH)GetStockObject(DC_BRUSH));
}
void roundBox(HDC dc, RECT r, int rad, COLORREF bg, COLORREF edge) {
    HGDIOBJ b = SelectObject(dc, GetStockObject(DC_BRUSH)), p = SelectObject(dc, GetStockObject(DC_PEN));
    SetDCBrushColor(dc, bg);
    SetDCPenColor(dc, edge);
    RoundRect(dc, r.left, r.top, r.right, r.bottom, rad, rad);
    SelectObject(dc, b);
    SelectObject(dc, p);
}
void drawText(HDC dc, const W &s, RECT r, HFONT f, COLORREF c, UINT flags) {
    auto old = SelectObject(dc, f);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, c);
    DrawTextW(dc, s.c_str(), static_cast<int>(s.size()), &r, flags | DT_NOPREFIX);
    SelectObject(dc, old);
}
fs::path chooseFolder(HWND w, const W &title) {
    Microsoft::WRL::ComPtr<IFileOpenDialog> dlg;
    if (FAILED(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dlg))))
        throw std::runtime_error("Windows folder picker unavailable.");
    DWORD flags{};
    dlg->GetOptions(&flags);
    dlg->SetOptions(flags | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_NOCHANGEDIR);
    dlg->SetTitle(title.c_str());
    if (FAILED(dlg->Show(w)))
        return {};
    Microsoft::WRL::ComPtr<IShellItem> item;
    if (FAILED(dlg->GetResult(&item)))
        return {};
    PWSTR path{};
    if (FAILED(item->GetDisplayName(SIGDN_FILESYSPATH, &path)))
        return {};
    fs::path result(path);
    CoTaskMemFree(path);
    return result;
}
fs::path chooseFile(HWND w, const W &title, const wchar_t *filters, bool save, W initial, const wchar_t *ext) {
    std::vector<wchar_t> buf(32768);
    wcsncpy_s(buf.data(), buf.size(), initial.c_str(), _TRUNCATE);
    OPENFILENAMEW of{sizeof(of)};
    of.hwndOwner = w;
    of.lpstrTitle = title.c_str();
    of.lpstrFilter = filters;
    of.lpstrFile = buf.data();
    of.nMaxFile = static_cast<DWORD>(buf.size());
    of.lpstrDefExt = ext;
    of.Flags =
        OFN_EXPLORER | OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST | (save ? OFN_OVERWRITEPROMPT : OFN_FILEMUSTEXIST);
    if (save ? GetSaveFileNameW(&of) : GetOpenFileNameW(&of))
        return fs::path(buf.data());
    if (CommDlgExtendedError())
        throw std::runtime_error("Windows file picker failed.");
    return {};
}

namespace {
struct Form {
    const W &title;
    std::vector<Field> &fields;
    HFONT font{};
};
INT_PTR CALLBACK formProc(HWND w, UINT m, WPARAM wp, LPARAM lp) {
    auto *f = reinterpret_cast<Form *>(GetWindowLongPtrW(w, DWLP_USER));
    if (m == WM_INITDIALOG) {
        f = reinterpret_cast<Form *>(lp);
        SetWindowLongPtrW(w, DWLP_USER, lp);
        SetWindowTextW(w, f->title.c_str());
        f->font = makeFont(w, 14);
        auto control = [&](const wchar_t *cls, const W &name, DWORD style, int id, int x, int y, int width,
                           int height, DWORD ex = 0) {
            HWND h = CreateWindowExW(ex, cls, name.c_str(), WS_CHILD | WS_VISIBLE | style, scaled(w, x),
                                     scaled(w, y), scaled(w, width), scaled(w, height), w,
                                     reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), instance, nullptr);
            SendMessageW(h, WM_SETFONT, reinterpret_cast<WPARAM>(f->font), TRUE);
            return h;
        };
        int y = 14;
        for (size_t i = 0; i < f->fields.size(); ++i) {
            const auto &field = f->fields[i];
            int id = 100 + static_cast<int>(i);
            control(L"STATIC", field.label, 0, 0, 18, y, 442, 20);
            if (field.choices.empty())
                control(L"EDIT", field.value, WS_TABSTOP | ES_AUTOHSCROLL, id, 18, y + 22, 442, 27,
                        WS_EX_CLIENTEDGE);
            else {
                HWND cb = control(WC_COMBOBOXW, L"", WS_TABSTOP | CBS_DROPDOWNLIST | WS_VSCROLL, id, 18, y + 22,
                                  442, 200);
                for (auto &item : field.choices)
                    SendMessageW(cb, CB_ADDSTRING, 0, (LPARAM)item.c_str());
                auto selected =
                    SendMessageW(cb, CB_FINDSTRINGEXACT, static_cast<WPARAM>(-1), (LPARAM)field.value.c_str());
                SendMessageW(cb, CB_SETCURSEL, selected < 0 ? 0 : selected, 0);
            }
            y += 58;
        }
        control(L"BUTTON", tr(L"确定", L"OK"), WS_TABSTOP | BS_DEFPUSHBUTTON, IDOK, 277, y + 3, 86, 31);
        control(L"BUTTON", tr(L"取消", L"Cancel"), WS_TABSTOP, IDCANCEL, 374, y + 3, 86, 31);
        RECT r{0, 0, scaled(w, 478), scaled(w, y + 49)};
        AdjustWindowRectExForDpi(&r, static_cast<DWORD>(GetWindowLongPtrW(w, GWL_STYLE)), FALSE,
                                 static_cast<DWORD>(GetWindowLongPtrW(w, GWL_EXSTYLE)), GetDpiForWindow(w));
        RECT parent{};
        GetWindowRect(GetParent(w), &parent);
        int width = r.right - r.left, height = r.bottom - r.top;
        SetWindowPos(w, nullptr, (parent.left + parent.right - width) / 2,
                     (parent.top + parent.bottom - height) / 2, width, height, SWP_NOZORDER);
        SetFocus(GetDlgItem(w, 100));
        SendDlgItemMessageW(w, 100, EM_SETSEL, 0, -1);
        return FALSE;
    }
    if (m == WM_COMMAND && (LOWORD(wp) == IDOK || LOWORD(wp) == IDCANCEL)) {
        if (LOWORD(wp) == IDOK)
            for (size_t i = 0; i < f->fields.size(); ++i)
                f->fields[i].value = windowText(GetDlgItem(w, 100 + static_cast<int>(i)));
        EndDialog(w, LOWORD(wp));
        return TRUE;
    }
    if (m == WM_CLOSE) {
        EndDialog(w, IDCANCEL);
        return TRUE;
    }
    return FALSE;
}
} // namespace
bool askFields(HWND w, const W &title, std::vector<Field> &fields) {
    struct {
        DLGTEMPLATE dlg;
        WORD menu, cls, title;
    } blank{};
    blank.dlg.style = WS_POPUP | WS_CAPTION | WS_SYSMENU | DS_MODALFRAME | DS_CENTER;
    blank.dlg.cx = 288;
    blank.dlg.cy = 120;
    Form f{title, fields};
    auto result = DialogBoxIndirectParamW(instance, &blank.dlg, w, formProc, reinterpret_cast<LPARAM>(&f));
    if (f.font)
        DeleteObject(f.font);
    return result == IDOK;
}

namespace {
struct OwnedHandle {
    HANDLE h{};
    ~OwnedHandle() {
        if (h && h != INVALID_HANDLE_VALUE)
            CloseHandle(h);
    }
    HANDLE take() {
        auto v = h;
        h = nullptr;
        return v;
    }
};
} // namespace
void Bridge::start(HWND w, const fs::path &root) {
    fs::path host = root / L"FxStudio.Win32Host.exe";
    SECURITY_ATTRIBUTES sa{sizeof(sa), nullptr, TRUE};
    OwnedHandle childIn, parentIn, parentOut, childOut;
    checkWin(CreatePipe(&childIn.h, &parentIn.h, &sa, 0), "Create input pipe");
    checkWin(CreatePipe(&parentOut.h, &childOut.h, &sa, 0), "Create output pipe");
    checkWin(SetHandleInformation(parentIn.h, HANDLE_FLAG_INHERIT, 0), "Input handle");
    checkWin(SetHandleInformation(parentOut.h, HANDLE_FLAG_INHERIT, 0), "Output handle");
    STARTUPINFOEXW si{};
    si.StartupInfo.cb = sizeof(si);
    si.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    si.StartupInfo.hStdInput = childIn.h;
    si.StartupInfo.hStdOutput = si.StartupInfo.hStdError = childOut.h;
    SIZE_T n{};
    InitializeProcThreadAttributeList(nullptr, 1, 0, &n);
    std::vector<BYTE> attrs(n);
    si.lpAttributeList = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(attrs.data());
    checkWin(InitializeProcThreadAttributeList(si.lpAttributeList, 1, 0, &n), "Process attributes");
    HANDLE inherited[]{childIn.h, childOut.h};
    BOOL ok = UpdateProcThreadAttribute(si.lpAttributeList, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherited,
                                        sizeof(inherited), nullptr, nullptr);
    PROCESS_INFORMATION pi{};
    W args = L"\"" + host.wstring() + L"\" \"" + root.wstring() + L"\"";
    if (ok)
        ok = CreateProcessW(host.c_str(), args.data(), nullptr, nullptr, TRUE,
                            CREATE_NO_WINDOW | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT, nullptr,
                            root.c_str(), &si.StartupInfo, &pi);
    DWORD err = GetLastError();
    DeleteProcThreadAttributeList(si.lpAttributeList);
    SetLastError(err);
    checkWin(ok, "Start FxStudio.Win32Host");
    OwnedHandle thread{pi.hThread};
    process_ = pi.hProcess;
    job_ = CreateJobObjectW(nullptr, nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    if (!job_ || !SetInformationJobObject(job_, JobObjectExtendedLimitInformation, &limits, sizeof(limits)) ||
        !AssignProcessToJobObject(job_, process_)) {
        TerminateProcess(process_, 1);
        throw std::runtime_error("Cannot supervise the SDK host process.");
    }
    ResumeThread(thread.h);
    input_ = parentIn.take();
    reader_ = std::thread([w, out = parentOut.take()] {
        OwnedHandle pipe{out};
        Str buffer;
        std::array<char, 8192> chunk{};
        DWORD count{};
        auto post = [&](Json msg) {
            auto *result = new Json(std::move(msg));
            if (!PostMessageW(w, WM_ENGINE, 0, (LPARAM)result))
                delete result;
        };
        while (ReadFile(out, chunk.data(), static_cast<DWORD>(chunk.size()), &count, nullptr) && count) {
            buffer.append(chunk.data(), count);
            size_t pos;
            while ((pos = buffer.find('\n')) != Str::npos) {
                Str row = buffer.substr(0, pos);
                buffer.erase(0, pos + 1);
                if (!row.empty() && row.back() == '\r')
                    row.pop_back();
                if (row.empty())
                    continue;
                Json msg = Json::parse(row, nullptr, false);
                if (msg.is_discarded() || !msg.is_object() || !msg.contains("kind"))
                    post({{"kind", "log"}, {"data", row}});
                else
                    post(std::move(msg));
            }
        }
        post({{"kind", "disconnected"}, {"data", ""}});
    });
}
void Bridge::send(const Json &request) {
    Str line = request.dump() + "\n";
    DWORD count{};
    if (!input_)
        throw std::runtime_error("The SDK host is offline.");
    checkWin(WriteFile(input_, line.data(), static_cast<DWORD>(line.size()), &count, nullptr) &&
                 count == line.size(),
             "Send to SDK host");
}
void Bridge::close() {
    if (input_) {
        CloseHandle(input_);
        input_ = nullptr;
    }
    if (process_)
        WaitForSingleObject(process_, 4000);
    if (job_) {
        CloseHandle(job_);
        job_ = nullptr;
    }
    if (process_) {
        CloseHandle(process_);
        process_ = nullptr;
    }
    if (reader_.joinable())
        reader_.join();
}
