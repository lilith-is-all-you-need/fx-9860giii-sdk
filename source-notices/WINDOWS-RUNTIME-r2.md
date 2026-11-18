# Windows runtime for FxStudio 0.2.0-r2

The Windows IDE and embedded Profile Studio shipped with 0.2.0-r2 use the self-contained .NET 10.0.12 runtime. RUNTIME-SOURCES.json in the release identifies the exact NuGet packages and their digests. The dotnet-notices/runtime-origin.json file under dist-toolchain/public-source-inputs records 10.0.15 from the earlier provisioning environment. For this Windows release use [dotnet/runtime](https://github.com/dotnet/runtime/tree/95017c711e6afc1085133d440e42b4bd78155701), [dotnet/wpf](https://github.com/dotnet/wpf/tree/v10.0.12) and [dotnet/winforms](https://github.com/dotnet/winforms/tree/v10.0.12).

独立发行的 FxProfile beta.4 与 SDK 内置的桌面程序分别打包。前者的自包含 .NET 运行时为 10.0.15，本 SDK 的运行时为 10.0.12。两者已分别做过准备和导出验证。
