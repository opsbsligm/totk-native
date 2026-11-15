FROM mcr.microsoft.com/dotnet/sdk:10.0.403-noble@sha256:de4fe90a98845d75910b9769662465c84de1a934665c431279d1382b2bddc02b AS dotnet
FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS system
ARG DEBIAN_FRONTEND=noninteractive
ARG JOBS=2
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git file xz-utils patchelf make cmake ninja-build pkg-config nasm \
    python3 python3-venv python3-dev clang-18 lld-18 llvm-18 g++ \
    libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxi-dev libxss-dev libxfixes-dev libxtst-dev \
    libxkbcommon-dev libwayland-dev wayland-protocols libdecor-0-dev libegl-dev libgl-dev libdrm-dev libgbm-dev \
    libpulse-dev libasound2-dev libpipewire-0.3-dev libdbus-1-dev libudev-dev libibus-1.0-dev \
    libvulkan-dev libssl-dev libopus-dev libvpx-dev libzstd-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/* \
    && for t in clang clang++ ld.lld llvm-ar llvm-nm llvm-ranlib llvm-strip; do ln -sf /usr/bin/$t-18 /usr/local/bin/$t; done

FROM system AS generator
COPY requirements-build.lock /opt/requirements-build.lock
RUN --mount=type=bind,from=distfiles,target=/distfiles,ro python3 -m venv /opt/venv \
    && if [ -d /distfiles/wheels ]; then /opt/venv/bin/pip install --no-index --find-links=/distfiles/wheels --only-binary=:all: --require-hashes -r /opt/requirements-build.lock; \
       else /opt/venv/bin/pip install --no-cache-dir --timeout 120 --retries 3 --only-binary=:all: --require-hashes -r /opt/requirements-build.lock; fi
ENV PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin

FROM system AS native-deps
ARG JOBS=2
COPY tools/build_deps.sh /opt/build_deps.sh
RUN --mount=type=bind,from=distfiles,target=/distfiles,ro mkdir -p /opt/native-deps && bash /opt/build_deps.sh x86_64 headers \
    && rm -rf /opt/native-deps/build/linux/src /opt/native-deps/build/linux/x86_64/deps-build
RUN --mount=type=bind,from=distfiles,target=/distfiles,ro mkdir -p /opt/native-deps && bash /opt/build_deps.sh x86_64 sdl \
    && rm -rf /opt/native-deps/build/linux/src /opt/native-deps/build/linux/x86_64/deps-build
RUN --mount=type=bind,from=distfiles,target=/distfiles,ro mkdir -p /opt/native-deps && bash /opt/build_deps.sh x86_64 ffmpeg \
    && rm -rf /opt/native-deps/build/linux/src /opt/native-deps/build/linux/x86_64/deps-build
RUN --mount=type=bind,from=distfiles,target=/distfiles,ro mkdir -p /opt/native-deps && bash /opt/build_deps.sh x86_64 shaderc \
    && rm -rf /opt/native-deps/build/linux/src /opt/native-deps/build/linux/x86_64/deps-build

FROM native-deps AS toolchain
COPY --from=generator /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin
ENV PKG_CONFIG_PATH=/opt/native-deps/build/linux/x86_64/deps/lib/pkgconfig
ENV LD_LIBRARY_PATH=/opt/native-deps/build/linux/x86_64/deps/lib
ENV ULTRS_VULKAN_INCLUDE=/opt/native-deps/build/linux/x86_64/deps/include
ENV NATIVE_DEPS=/opt/native-deps/build/linux/x86_64/deps
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /src

COPY --from=dotnet /usr/share/dotnet /usr/share/dotnet
RUN ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet

RUN sed -i \
      -e 's|http://archive.ubuntu.com/ubuntu|https://archive.ubuntu.com/ubuntu|' \
      -e 's|http://security.ubuntu.com/ubuntu|https://security.ubuntu.com/ubuntu|' \
      /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-wqy-microhei \
      "libclang-rt-18-dev=$(dpkg-query -W -f='${Version}' clang-18)" \
    && rm -rf /var/lib/apt/lists/*

# Dependency installation is complete. Build execution never installs packages.
RUN /opt/venv/bin/python -m pip uninstall --yes pip
