#include <gint/display.h>
#include <gint/keyboard.h>
#include <array>

template<class T, unsigned N>
T sum(const std::array<T, N>& values)
{
    T result{};
    for (T value : values) result += value;
    return result;
}

int main()
{
    const std::array<int, 3> values{3, 5, 7};
    int answer = sum<int, 3>(values);
    dclear(C_WHITE);
    dtext(4, 4, C_BLACK, "FX IDE - C++17");
    dprint(4, 22, C_BLACK, "3 + 5 + 7 = %d", answer);
    dtext(4, 44, C_BLACK, "EXIT: quit");
    dupdate();
    while (getkey().key != KEY_EXIT) {}
    return 0;
}
