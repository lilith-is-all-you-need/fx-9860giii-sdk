using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using FxStudio.Core;

internal static class NativeBuildContract
{
    public static async Task RunAsync(string sdkDirectory, string evidenceDirectory)
    {
        var evidence = Path.GetFullPath(evidenceDirectory);
        Directory.CreateDirectory(evidence);
        var work = Path.Combine(evidence, "contract-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(work);
        var records = new List<object>();
        var builder = new BuildService();
        builder.Log += Console.WriteLine;
        foreach (var test in new[] { "failure", "cancel" }) {
            var source = Path.Combine(work, test); Directory.CreateDirectory(source);
            var cmake = test == "failure"
                ? "cmake_minimum_required(VERSION 3.15)\nproject(contract C)\nmessage(FATAL_ERROR \"Intentional build-contract failure\")\n"
                : "cmake_minimum_required(VERSION 3.15)\nproject(contract C)\nexecute_process(COMMAND \"${CMAKE_COMMAND}\" -E echo FXIDE_TEST_SLEEP_READY)\nexecute_process(COMMAND \"${CMAKE_COMMAND}\" -E sleep 8)\nfile(WRITE \"${CMAKE_SOURCE_DIR}/cancel-survived.txt\" \"child was not cancelled\")\nmessage(FATAL_ERROR \"Should have been cancelled\")\n";
            var sourceFile = Path.Combine(source, "CMakeLists.txt"); await File.WriteAllTextAsync(sourceFile, cmake);
            var before = SHA256.HashData(await File.ReadAllBytesAsync(sourceFile));
            var output = Path.Combine(source, ".fxstudio", "build"); var profile = Path.Combine(output, "Debug"); Directory.CreateDirectory(profile);
            var manifest = Path.Combine(profile, "artifact.json"); await File.WriteAllTextAsync(manifest, "{\"stale\":true}");
            var config = new ProjectConfig { Name = test, SourceDirectory = source, BuildDirectory = output, Backend = "native", NativeSdkDirectory = Path.GetFullPath(sdkDirectory) };
            using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            void CancelOnReady(string line) { if (test == "cancel" && line == "FXIDE_TEST_SLEEP_READY") cancellation.Cancel(); }
            builder.Log += CancelOnReady;
            var elapsed = Stopwatch.StartNew();
            var expectedFailure = false;
            try { await builder.BuildAsync(config, BuildConfiguration.Debug, cancellation.Token); }
            catch (BuildException) when (test == "failure") { expectedFailure = true; }
            catch (OperationCanceledException) when (test == "cancel" && cancellation.IsCancellationRequested) { expectedFailure = true; }
            finally { builder.Log -= CancelOnReady; }
            if (!expectedFailure || File.Exists(manifest)) throw new Exception(test + ": failed build retained success state");
            var after = SHA256.HashData(await File.ReadAllBytesAsync(sourceFile));
            if (!before.SequenceEqual(after)) throw new Exception(test + ": original source was changed");
            if (test == "cancel") {
                await Task.Delay(TimeSpan.FromSeconds(9));
                // The sentinel would be written by the staged CMake process if it survived cancellation.
                var cache = Path.Combine(Path.GetTempPath(), "FxStudio-native");
                var candidates = Directory.EnumerateFiles(cache, "cancel-survived.txt", SearchOption.AllDirectories);
                if (candidates.Any()) throw new Exception("A cancelled native build process survived and wrote its sentinel.");
            }
            records.Add(new { test, passed = true, seconds = elapsed.Elapsed.TotalSeconds, staleManifestRemoved = true, originalSourcePreserved = true });
        }
        await File.WriteAllTextAsync(Path.Combine(evidence, "native-build-contract.json"), JsonSerializer.Serialize(new { passed = true, checks = records }, new JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine("PASS: native build failure/cancellation contract and process-tree cleanup");
    }
}
