FROM ros:jazzy-ros-base@sha256:c3706ef0a0aa45413c07803cf433602f543b22e45b4855f6fca955c2d8ecc4e8
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    python3-pip python3-pytest python3-serial python3-websocket python3-websockets tmux \
    ros-jazzy-diagnostic-msgs ros-jazzy-rosidl-default-generators \
    ros-jazzy-ament-lint-common ros-jazzy-ament-lint-auto && \
    python3 -m pip install --break-system-packages 'martypy==3.7.2' && \
    rm -rf /var/lib/apt/lists/*
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    ros-jazzy-rviz2 ros-jazzy-tf2-ros ros-jazzy-visualization-msgs \
    xvfb x11-utils fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /ws
