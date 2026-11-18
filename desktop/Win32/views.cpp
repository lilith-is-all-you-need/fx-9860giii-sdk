#include "studio.h"
#include <wincodec.h>

using Microsoft::WRL::ComPtr;
namespace {
void requireHr(HRESULT hr, const char *label) {
    if (FAILED(hr))
        throw std::runtime_error(Str(label) + " (" + std::to_string(static_cast<unsigned>(hr)) + ")");
}
W crlf(const W &s) {
    W out;
    for (auto c : s)
        if (c != L'\r') {
            if (c == L'\n')
                out += L'\r';
            out += c;
        }
    return out;
}
} // namespace
std::shared_ptr<Gdiplus::Bitmap> loadImage(const fs::path &path, bool screen, UINT *nframes) {
    ComPtr<IWICImagingFactory> factory;
    requireHr(CoCreateInstance(CLSID_WICImagingFactory, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory)),
              "Windows Imaging Component");
    auto bytes = readBytes(path, screen ? 1048576 : 64ull * 1024 * 1024);
    if (bytes.empty())
        throw std::runtime_error("Empty image.");
    ComPtr<IWICStream> stream;
    requireHr(factory->CreateStream(&stream), "Image stream");
    requireHr(
        stream->InitializeFromMemory(reinterpret_cast<BYTE *>(bytes.data()), static_cast<DWORD>(bytes.size())),
        "Initialize image");
    ComPtr<IWICBitmapDecoder> decoder;
    requireHr(factory->CreateDecoderFromStream(stream.Get(), nullptr, WICDecodeMetadataCacheOnDemand, &decoder),
              "Decode image");
    if (nframes)
        decoder->GetFrameCount(nframes);
    ComPtr<IWICBitmapFrameDecode> frame;
    requireHr(decoder->GetFrame(0, &frame), "First frame");
    UINT w{}, h{};
    requireHr(frame->GetSize(&w, &h), "Image size");
    if (!w || !h || uint64_t(w) * h > 16000000 || (screen && (w != 128 || h != 64)))
        throw std::runtime_error("Unsupported image dimensions.");
    ComPtr<IWICFormatConverter> conv;
    requireHr(factory->CreateFormatConverter(&conv), "Pixel converter");
    requireHr(conv->Initialize(frame.Get(), GUID_WICPixelFormat32bppPBGRA, WICBitmapDitherTypeNone, nullptr, 0,
                               WICBitmapPaletteTypeCustom),
              "Image format");
    auto bitmap = std::make_shared<Gdiplus::Bitmap>(w, h, PixelFormat32bppPARGB);
    Gdiplus::BitmapData bits{};
    Gdiplus::Rect r(0, 0, w, h);
    if (bitmap->LockBits(&r, Gdiplus::ImageLockModeWrite, PixelFormat32bppPARGB, &bits) != Gdiplus::Ok)
        throw std::runtime_error("Create image bitmap.");
    auto hr = conv->CopyPixels(nullptr, bits.Stride, bits.Stride * h, static_cast<BYTE *>(bits.Scan0));
    bitmap->UnlockBits(&bits);
    requireHr(hr, "Copy image pixels");
    return bitmap;
}
void savePng(Gdiplus::Bitmap &image, const fs::path &path) {
    GUID png{0x557cf406, 0x1a04, 0x11d3, {0x9a, 0x73, 0, 0, 0xf8, 0x1e, 0xf3, 0x2e}};
    ComPtr<IStream> stream;
    requireHr(CreateStreamOnHGlobal(nullptr, TRUE, &stream), "PNG stream");
    if (image.Save(stream.Get(), &png, nullptr) != Gdiplus::Ok)
        throw std::runtime_error("PNG encoding failed.");
    STATSTG stat{};
    requireHr(stream->Stat(&stat, STATFLAG_NONAME), "PNG size");
    LARGE_INTEGER start{};
    stream->Seek(start, STREAM_SEEK_SET, nullptr);
    Str bytes(stat.cbSize.LowPart, 0);
    ULONG n{};
    requireHr(stream->Read(bytes.data(), static_cast<ULONG>(bytes.size()), &n), "Read encoded PNG");
    if (n != bytes.size())
        throw std::runtime_error("Incomplete PNG.");
    atomicWrite(path, bytes);
}
namespace {
enum class View { Image, Screen, Library, Text, Members };
struct Auxiliary {
    View type;
    W title, info, content;
    HWND window{}, field{}, list{}, body{}, summary{};
    HFONT font{}, mono{};
    std::shared_ptr<Gdiplus::Bitmap> bitmap;
    std::shared_ptr<Gdiplus::Bitmap> *live{};
    int zoom = 1, offsetX{}, offsetY{};
    UINT frames = 1;
    struct Reference {
        W title, details, search;
    };
    std::vector<Reference> reference;
    std::vector<int> matches;
    Studio *studio{};
    W expression;
    std::map<std::vector<int>, HTREEITEM> memberItems;
    std::map<HTREEITEM, std::vector<int>> memberTrails;
    std::set<HTREEITEM> populated;
    explicit Auxiliary(View v) : type(v) {}
};
W downcase(W s) {
    std::transform(s.begin(), s.end(), s.begin(), towlower);
    return s;
}
HWND child(Auxiliary &a, const wchar_t *cls, const W &label, DWORD style, int id, DWORD ex = 0) {
    auto c = CreateWindowExW(ex, cls, label.c_str(), WS_CHILD | WS_VISIBLE | style, 0, 0, 0, 0, a.window,
                             (HMENU)(INT_PTR)id, instance, nullptr);
    SendMessageW(c, WM_SETFONT, (WPARAM)a.font, TRUE);
    return c;
}
void detail(Auxiliary &a) {
    auto i = SendMessageW(a.list, LB_GETCURSEL, 0, 0);
    SetWindowTextW(a.body, i >= 0 && i < (int)a.matches.size() ? a.reference[a.matches[i]].details.c_str() : L"");
}
void filter(Auxiliary &a) {
    auto q = downcase(windowText(a.field));
    a.matches.clear();
    SendMessageW(a.list, WM_SETREDRAW, FALSE, 0);
    SendMessageW(a.list, LB_RESETCONTENT, 0, 0);
    for (int i = 0; i < (int)a.reference.size(); ++i)
        if (a.reference[i].search.find(q) != W::npos) {
            a.matches.push_back(i);
            SendMessageW(a.list, LB_ADDSTRING, 0, (LPARAM)a.reference[i].title.c_str());
        }
    SendMessageW(a.list, LB_SETCURSEL, 0, 0);
    SendMessageW(a.list, WM_SETREDRAW, TRUE, 0);
    InvalidateRect(a.list, nullptr, TRUE);
    detail(a);
    SetWindowTextW(a.summary, (std::to_wstring(a.matches.size()) + tr(L" 条结果", L" results")).c_str());
}
void resize(Auxiliary &a) {
    RECT r{};
    GetClientRect(a.window, &r);
    auto u = [&](int n) { return scaled(a.window, n); };
    int w = r.right, h = r.bottom;
    if (a.type == View::Library) {
        int col = std::clamp(w * 39 / 100, u(148), u(370));
        MoveWindow(a.field, u(14), u(12), std::max(20, w - u(148)), u(29), TRUE);
        MoveWindow(a.summary, w - u(125), u(16), u(113), u(22), TRUE);
        MoveWindow(a.list, u(14), u(51), col, std::max(12, h - u(65)), TRUE);
        MoveWindow(a.body, col + u(24), u(51), std::max(25, w - col - u(38)), std::max(12, h - u(65)), TRUE);
    } else if (a.type == View::Text || a.type == View::Members) {
        MoveWindow(a.body, u(13), u(13), std::max(8, w - u(26)), std::max(8, h - u(26)), TRUE);
    } else {
        MoveWindow(a.field, u(13), u(10), u(90), u(210), TRUE);
        MoveWindow(a.summary, u(118), u(13), std::max(60, w - u(a.type == View::Screen ? 256 : 130)), u(27), TRUE);
        if (a.type == View::Screen)
            MoveWindow(GetDlgItem(a.window, 6), w - u(116), u(9), u(103), u(29), TRUE);
        if (a.type == View::Image && a.bitmap) {
            auto set = [&](int bar, int total, int visible, int &current) {
                SCROLLINFO si{sizeof(si), SIF_RANGE | SIF_PAGE | SIF_POS};
                si.nMin = 0;
                si.nMax = std::max(0, total - 1);
                si.nPage = std::max(1, visible);
                si.nPos = current;
                current = SetScrollInfo(a.window, bar, &si, TRUE);
            };
            set(SB_HORZ, a.bitmap->GetWidth() * a.zoom, w, a.offsetX);
            set(SB_VERT, a.bitmap->GetHeight() * a.zoom, std::max(1, h - u(50)), a.offsetY);
        }
    }
    InvalidateRect(a.window, nullptr, TRUE);
}
LRESULT CALLBACK auxProc(HWND h, UINT m, WPARAM wp, LPARAM lp) {
    auto *a = reinterpret_cast<Auxiliary *>(GetWindowLongPtrW(h, GWLP_USERDATA));
    if (m == WM_NCCREATE) {
        a = static_cast<Auxiliary *>(reinterpret_cast<CREATESTRUCTW *>(lp)->lpCreateParams);
        a->window = h;
        SetWindowLongPtrW(h, GWLP_USERDATA, (LONG_PTR)a);
    }
    if (!a)
        return DefWindowProcW(h, m, wp, lp);
    switch (m) {
    case WM_CREATE: {
        a->font = makeFont(h, 14);
        a->mono = makeFont(h, 14, FW_NORMAL, L"Consolas");
        if (a->type == View::Library) {
            a->field = child(*a, L"EDIT", L"", WS_TABSTOP | ES_AUTOHSCROLL, 1, WS_EX_CLIENTEDGE);
            SendMessageW(
                a->field, EM_SETCUEBANNER, TRUE,
                (LPARAM)tr(L"搜索主题、地址、系统调用…", L"Search topics, addresses or system calls…").c_str());
            a->summary = child(*a, L"STATIC", L"", SS_RIGHT, 5);
            a->list = child(*a, L"LISTBOX", L"", LBS_NOTIFY | LBS_NOINTEGRALHEIGHT | WS_VSCROLL | WS_TABSTOP, 2,
                            WS_EX_CLIENTEDGE);
            a->body =
                child(*a, L"EDIT", L"", ES_READONLY | ES_MULTILINE | WS_VSCROLL | WS_TABSTOP, 3, WS_EX_CLIENTEDGE);
            filter(*a);
            SetFocus(a->field);
        } else if (a->type == View::Members) {
            a->body = child(*a, WC_TREEVIEWW, L"",
                            TVS_HASBUTTONS | TVS_HASLINES | TVS_LINESATROOT | TVS_SHOWSELALWAYS | WS_TABSTOP, 3,
                            WS_EX_CLIENTEDGE);
            a->studio->variableView = h;
            EnableWindow(GetParent(h), FALSE);
            SetFocus(a->body);
        } else if (a->type == View::Text) {
            a->body = child(*a, L"EDIT", crlf(a->content), ES_READONLY | ES_MULTILINE | WS_VSCROLL | WS_TABSTOP, 3);
            SendMessageW(a->body, WM_SETFONT, (WPARAM)a->mono, FALSE);
        } else {
            a->field = child(*a, WC_COMBOBOXW, L"", CBS_DROPDOWNLIST | WS_TABSTOP, 1);
            for (auto n : {1, 2, 3, 4, 6, 8, 10}) {
                W text = std::to_wstring(n) + L" ×";
                auto i = SendMessageW(a->field, CB_ADDSTRING, 0, (LPARAM)text.c_str());
                SendMessageW(a->field, CB_SETITEMDATA, i, n);
                if (n == a->zoom)
                    SendMessageW(a->field, CB_SETCURSEL, i, 0);
            }
            a->summary = child(*a, L"STATIC", a->info, 0, 5);
            if (a->live) {
                child(*a, L"BUTTON", tr(L"保存 PNG", L"Save PNG"), WS_TABSTOP, 6);
                SetTimer(h, 1, 100, nullptr);
            }
        }
        resize(*a);
        return 0;
    }
    case WM_GETMINMAXINFO:
        reinterpret_cast<MINMAXINFO *>(lp)->ptMinTrackSize = {scaled(h, 350), scaled(h, 230)};
        return 0;
    case WM_SIZE:
        if (a->font)
            resize(*a);
        return 0;
    case WM_COMMAND:
        if (a->type == View::Library) {
            if (LOWORD(wp) == 1 && HIWORD(wp) == EN_CHANGE)
                filter(*a);
            if (LOWORD(wp) == 2 && HIWORD(wp) == LBN_SELCHANGE)
                detail(*a);
        } else if (LOWORD(wp) == 1 && HIWORD(wp) == CBN_SELCHANGE) {
            a->zoom = (int)SendMessageW(a->field, CB_GETITEMDATA, SendMessageW(a->field, CB_GETCURSEL, 0, 0), 0);
            resize(*a);
        } else if (LOWORD(wp) == 6 && a->bitmap) {
            try {
                auto path = chooseFile(h, tr(L"保存原始屏幕", L"Save native-resolution screen"), L"PNG\0*.png\0",
                                       true, L"fx-screen.png", L"png");
                if (!path.empty())
                    savePng(*a->bitmap, path);
            } catch (const std::exception &ex) {
                failure(h, wide(ex.what()));
            }
        }
        return 0;
    case WM_NOTIFY:
        if (a->type == View::Members && reinterpret_cast<NMHDR *>(lp)->code == TVN_ITEMEXPANDINGW) {
            auto ev = reinterpret_cast<NMTREEVIEWW *>(lp);
            auto item = ev->itemNew.hItem;
            if (ev->action == TVE_EXPAND && !a->populated.count(item)) {
                auto found = a->memberTrails.find(item);
                if (found != a->memberTrails.end() && a->studio->paused && !a->studio->busy) {
                    try {
                        a->studio->request("children",
                                           {{"expression", utf8(a->expression)}, {"trail", found->second}});
                    } catch (const std::exception &err) {
                        a->studio->commandError(err);
                    }
                }
                return TRUE;
            }
        }
        break;
    case WM_TIMER:
        if (a->live && a->bitmap != *a->live) {
            a->bitmap = *a->live;
            InvalidateRect(h, nullptr, FALSE);
        }
        return 0;
    case WM_VSCROLL:
    case WM_HSCROLL: {
        int bar = m == WM_VSCROLL ? SB_VERT : SB_HORZ;
        SCROLLINFO si{sizeof(si), SIF_ALL};
        GetScrollInfo(h, bar, &si);
        int v = si.nPos;
        switch (LOWORD(wp)) {
        case SB_LINEUP:
            v -= 20;
            break;
        case SB_LINEDOWN:
            v += 20;
            break;
        case SB_PAGEUP:
            v -= si.nPage;
            break;
        case SB_PAGEDOWN:
            v += si.nPage;
            break;
        case SB_THUMBTRACK:
            v = si.nTrackPos;
            break;
        }
        (bar == SB_VERT ? a->offsetY : a->offsetX) = SetScrollPos(h, bar, v, TRUE);
        si.fMask = SIF_POS;
        GetScrollInfo(h, bar, &si);
        (bar == SB_VERT ? a->offsetY : a->offsetX) = si.nPos;
        InvalidateRect(h, nullptr, FALSE);
        return 0;
    }
    case WM_MOUSEWHEEL:
        if (a->type == View::Image) {
            SendMessageW(h, WM_VSCROLL, GET_WHEEL_DELTA_WPARAM(wp) > 0 ? SB_LINEUP : SB_LINEDOWN, 0);
            return 0;
        }
        break;
    case WM_PAINT: {
        PAINTSTRUCT ps{};
        auto dc = BeginPaint(h, &ps);
        RECT r{};
        GetClientRect(h, &r);
        fill(dc, r, surface);
        if ((a->type == View::Image || a->type == View::Screen) && a->bitmap) {
            int top = scaled(h, 50);
            RECT body{0, top, r.right, r.bottom};
            fill(dc, body, a->live ? RGB(39, 59, 60) : RGB(230, 236, 232));
            auto &b = *a->bitmap;
            int w = b.GetWidth() * a->zoom, hh = b.GetHeight() * a->zoom;
            int x = std::max(0, ((int)r.right - w) / 2) - a->offsetX,
                y = top + std::max(0, ((int)r.bottom - top - hh) / 2) - a->offsetY;
            SaveDC(dc);
            IntersectClipRect(dc, 0, top, r.right, r.bottom);
            if (!a->live) {
                for (int yy = std::max(top, y); yy < std::min<int>(r.bottom, y + hh); yy += 8)
                    for (int xx = std::max(0, x); xx < std::min<int>(r.right, x + w); xx += 8)
                        fill(dc, {xx, yy, std::min(xx + 8, x + w), std::min(yy + 8, y + hh)},
                             (((xx - std::max(0, x)) / 8 + (yy - std::max(top, y)) / 8) & 1) ? RGB(219, 227, 221)
                                                                                             : paper);
            }
            {
                Gdiplus::Graphics g(dc);
                g.SetInterpolationMode(Gdiplus::InterpolationModeNearestNeighbor);
                g.SetPixelOffsetMode(Gdiplus::PixelOffsetModeHalf);
                g.DrawImage(&b, x, y, w, hh);
            }
            RestoreDC(dc, -1);
        }
        EndPaint(h, &ps);
        return 0;
    }
    case WM_CTLCOLORSTATIC:
        SetBkColor((HDC)wp, surface);
        SetTextColor((HDC)wp, ink);
        SetDCBrushColor((HDC)wp, surface);
        return (LRESULT)GetStockObject(DC_BRUSH);
    case WM_DESTROY:
        KillTimer(h, 1);
        if (a->type == View::Members) {
            a->studio->variableView = nullptr;
            EnableWindow(GetParent(h), TRUE);
            SetActiveWindow(GetParent(h));
        }
        break;
    case WM_NCDESTROY:
        if (a->font)
            DeleteObject(a->font);
        if (a->mono)
            DeleteObject(a->mono);
        SetWindowLongPtrW(h, GWLP_USERDATA, 0);
        delete a;
        break;
    }
    return DefWindowProcW(h, m, wp, lp);
}
void show(HWND owner, std::unique_ptr<Auxiliary> v) {
    static bool registered = false;
    if (!registered) {
        WNDCLASSEXW c{sizeof(c)};
        c.hInstance = instance;
        c.lpszClassName = L"FxStudio.NativeInspector";
        c.lpfnWndProc = auxProc;
        c.hCursor = LoadCursor(nullptr, IDC_ARROW);
        c.hIcon = LoadIconW(instance, MAKEINTRESOURCEW(101));
        RegisterClassExW(&c);
        registered = true;
    }
    RECT r{};
    GetWindowRect(owner, &r);
    int w = scaled(owner, v->type == View::Library ? 890 : 720),
        h = scaled(owner, v->type == View::Library ? 565 : 455);
    DWORD style = WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN;
    if (v->type == View::Image)
        style |= WS_VSCROLL | WS_HSCROLL;
    W title = v->title;
    auto *raw = v.release();
    HWND window = CreateWindowExW(0, L"FxStudio.NativeInspector", title.c_str(), style,
                                  r.left + std::max(8, ((int)(r.right - r.left) - w) / 2),
                                  r.top + std::max(8, ((int)(r.bottom - r.top) - h) / 2), w, h, owner, nullptr,
                                  instance, raw);
    checkWin(window != nullptr, "Open inspector");
    ShowWindow(window, SW_SHOW);
    UpdateWindow(window);
}
} // namespace
void detailWindow(HWND owner, const W &title, const W &text) {
    auto a = std::make_unique<Auxiliary>(View::Text);
    a->title = title;
    a->content = text;
    show(owner, std::move(a));
}
void imageWindow(HWND owner, const fs::path &path, bool) {
    auto a = std::make_unique<Auxiliary>(View::Image);
    a->title = path.filename().wstring() + L" · " + tr(L"资源预览", L"Resource preview");
    a->bitmap = loadImage(path, false, &a->frames);
    a->zoom = a->bitmap->GetWidth() <= 128 ? 4 : 1;
    a->info = std::to_wstring(a->bitmap->GetWidth()) + L" × " + std::to_wstring(a->bitmap->GetHeight()) +
              L" px  ·  " + std::to_wstring(fs::file_size(path)) + L" B";
    if (a->frames > 1)
        a->info += tr(L"  ·  首帧 / ", L"  ·  first frame / ") + std::to_wstring(a->frames);
    show(owner, std::move(a));
}
void screenWindow(HWND owner, std::shared_ptr<Gdiplus::Bitmap> *screen) {
    auto a = std::make_unique<Auxiliary>(View::Screen);
    a->title = tr(L"计算器屏幕", L"Calculator screen");
    a->live = screen;
    a->bitmap = *screen;
    a->zoom = 4;
    a->info = L"fx-9860GIII  ·  128 × 64 px";
    show(owner, std::move(a));
}
void knowledgeWindow(HWND owner, const fs::path &root) {
    auto a = std::make_unique<Auxiliary>(View::Library);
    a->title = tr(L"计算器资料库", L"Calculator reference");
    auto add = [&](W title, W body) {
        auto detail = crlf(title + L"\n\n" + body);
        a->reference.push_back({title, detail, downcase(detail)});
    };
    for (auto &v : Json::parse(readBytes(root / L"docs/CalculatorKnowledge.json")))
        add(val(v, "Title"), val(v, "Evidence") + L"\n\n" + val(v, "Text") + L"\n\n" + val(v, "Source"));
    auto syscalls = Json::parse(readBytes(root / L"docs/syscall-coverage.json"));
    for (auto &v : syscalls.at("entries")) {
        W name = val(v, "number");
        W desc = val(v, "name");
        if (!desc.empty())
            name += L" · " + desc;
        add(name, val(v, "status") + L"\n\n" + wide(v.dump(2)));
    }
    show(owner, std::move(a));
}

void Studio::inspectMembers(const Json &result) {
    auto trail = result.at("trail").get<std::vector<int>>();
    if (!variableView) {
        if (!trail.empty())
            return;
        auto a = std::make_unique<Auxiliary>(View::Members);
        a->studio = this;
        a->expression = val(result, "expression");
        a->title = tr(L"变量成员", L"Variable members") + L" · " + a->expression;
        show(win, std::move(a));
    }
    auto *a = reinterpret_cast<Auxiliary *>(GetWindowLongPtrW(variableView, GWLP_USERDATA));
    auto add = [&](HTREEITEM parent, const Json &value, const std::vector<int> &path) {
        W label = val(value, "name") + L"   " + val(value, "type") + L"   " + val(value, "value");
        TVINSERTSTRUCTW item{};
        item.hParent = parent;
        item.hInsertAfter = TVI_LAST;
        item.item.mask = TVIF_TEXT | TVIF_CHILDREN;
        item.item.pszText = label.data();
        item.item.cChildren =
            value.value("children", Json(nullptr)).is_number() && value["children"].get<int>() > 0;
        auto handle = TreeView_InsertItem(a->body, &item);
        a->memberItems[path] = handle;
        a->memberTrails[handle] = path;
        return handle;
    };
    if (trail.empty() && a->memberItems.empty())
        add(TVI_ROOT, result.at("variable"), trail);
    auto it = a->memberItems.find(trail);
    if (it == a->memberItems.end() || a->populated.count(it->second))
        return;
    auto parent = it->second;
    int index = 0;
    for (auto &child : result.at("items")) {
        auto path = trail;
        path.push_back(index++);
        add(parent, child, path);
    }
    a->populated.insert(parent);
    TreeView_Expand(a->body, parent, TVE_EXPAND);
}
