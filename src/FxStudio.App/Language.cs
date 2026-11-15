using System.Windows;

namespace FxStudio.App;

internal static class Language
{
    public static bool Chinese { get; private set; }
    public static string Text(string en, string zh) => Chinese ? zh : en;
    public static void Set(string language)
    {
        Chinese = language.StartsWith("zh", StringComparison.OrdinalIgnoreCase);
        var pairs = new Dictionary<string, (string en, string zh)>
        {
            ["File"]=("File", "文件"), ["New"]=("New C/C++ project…", "新建 C/C++ 工程…"), ["Open"]=("Open project…", "打开工程…"),
            ["Save"]=("Save", "保存"), ["SaveAll"]=("Save all", "保存全部"), ["Demo"]=("Open example", "打开示例"), ["Exit"]=("Exit", "退出"),
            ["Build"]=("Build", "构建"), ["BuildProject"]=("Build project", "构建工程"), ["CancelBuild"]=("Cancel build", "取消构建"),
            ["Run"]=("Debug", "调试"), ["Start"]=("Start / Continue", "启动 / 继续"), ["Pause"]=("Pause", "暂停"), ["Stop"]=("Stop", "停止"),
            ["Step"]=("Step into", "单步进入"), ["Next"]=("Step over", "单步越过"), ["Finish"]=("Step out", "跳出"), ["RunTo"]=("Run to cursor", "运行到光标"),
            ["Breakpoint"]=("Toggle breakpoint", "切换断点"), ["Restart"]=("Restart", "重新启动"),
            ["StepInstruction"]=("Step instruction", "单条指令进入"), ["NextInstruction"]=("Step over instruction", "单条指令越过"),
            ["ToggleEnabled"]=("Enable / disable", "启用 / 禁用"),
            ["EnlargeScreen"]=("Enlarge…", "放大画面…"), ["SaveScreen"]=("Save PNG…", "保存 PNG…"),
            ["InspectHint"]=("Double-click a value to inspect members. Values update when paused.", "双击变量查看成员；暂停后更新数值。"),
            ["ImportBuild"]=("Load compiled program…", "加载已有编译产物…"),
            ["Tools"]=("Tools", "工具"), ["Settings"]=("Settings…", "设置…"), ["Reveal"]=("Show build folder", "打开构建目录"), ["Help"]=("Help", "帮助"), ["Guide"]=("User guide", "使用说明"),
            ["Project"]=("PROJECT", "工程"), ["Calculator"]=("CALCULATOR", "计算器"), ["Target"]=("fx-9860GIII · SuperH", "fx-9860GIII · SuperH"),
            ["PreviewHint"]=("Real target execution · 128 × 64", "目标程序运行画面 · 128 × 64"), ["PreviewEmpty"]=("Build and start to preview", "构建并启动以查看画面"),
            ["KeyHint"]=("Calculator keys are available while running.", "程序运行时可操作计算器按键。"),
            ["Output"]=("Build output", "构建输出"), ["Locals"]=("Locals", "局部变量"), ["Watch"]=("Watch", "观察"), ["Stack"]=("Call stack", "调用栈"),
            ["Registers"]=("Registers", "寄存器"), ["Memory"]=("Memory", "内存"), ["Disassembly"]=("Disassembly", "反汇编"), ["Breakpoints"]=("Breakpoints", "断点"),
            ["Add"]=("Add", "添加"), ["Remove"]=("Remove", "移除"), ["Refresh"]=("Read", "读取"), ["Condition"]=("Condition…", "条件…"), ["Watchpoint"]=("Data watchpoint…", "数据监视点…"),
            ["EditValue"]=("Set value…", "设置值…"), ["Welcome"]=("Open a project or try the included example.", "打开工程，或尝试附带示例。"),
            ["StatusReady"]=("Ready", "就绪"), ["Configuration"]=("Configuration", "构建配置"), ["Find"]=("Find…", "查找…"), ["Export"]=("Export G1A…", "导出 G1A…")
        };
        foreach (var (key, pair) in pairs) Application.Current.Resources[key] = Chinese ? pair.zh : pair.en;
    }
}
