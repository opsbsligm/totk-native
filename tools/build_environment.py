"""Keep build-only .NET and NuGet state in the chosen external workspace."""
import os
from pathlib import Path
import stat


def prepare(work):
    work = Path(work)
    info = work.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022):
        raise ValueError('Build workspace must be an ordinary directory owned by the build user')
    runtime = work / '.build-runtime'
    paths = {
        'DOTNET_CLI_HOME': runtime / 'cli-home',
        'XDG_RUNTIME_DIR': runtime,
        'XDG_DATA_HOME': runtime / 'data',
        'XDG_CONFIG_HOME': runtime / 'config',
        'XDG_CACHE_HOME': work / 'cache',
        'NUGET_PACKAGES': work / 'cache/nuget',
        'NUGET_HTTP_CACHE_PATH': work / 'cache/nuget-http',
        'NUGET_SCRATCH': runtime / 'nuget',
        'DOTNET_BUNDLE_EXTRACT_BASE_DIR': work / 'cache/dotnet-extract',
    }
    for target in dict.fromkeys(paths.values()):
        current = work
        for name in target.relative_to(work).parts:
            current = current / name
            current.mkdir(mode=0o700, exist_ok=True)
            info = current.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o022):
                raise ValueError('Build state path is linked, non-directory or owned by another user')
            if current == runtime and stat.S_IMODE(info.st_mode) != 0o700:
                raise ValueError('Build runtime directory must have owner-only permissions')
    return {key: str(path) for key, path in paths.items()}
