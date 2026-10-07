FROM axiom-marty-demo-core:jazzy
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    x11vnc novnc websockify openbox tint2 xterm dbus-x11 adwaita-icon-theme \
    wget gnupg ca-certificates && rm -rf /var/lib/apt/lists/*
# Mozilla's signed DEB works in a container without Ubuntu's Snap daemon.
RUN install -d -m 0755 /etc/apt/keyrings && \
    wget -q https://packages.mozilla.org/apt/repo-signing-key.gpg \
      -O /etc/apt/keyrings/packages.mozilla.org.asc && \
    gpg --batch --show-keys --with-colons /etc/apt/keyrings/packages.mozilla.org.asc \
      | grep -q '^fpr:::::::::35BAA0B33E9EB396F59CA838C0BA5CE6DC6315A3:'
RUN printf '%s\n' \
      'deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main' \
      > /etc/apt/sources.list.d/mozilla.list && \
    apt-get update -qq && apt-get install -y --no-install-recommends firefox-esr && \
    rm -rf /var/lib/apt/lists/* && \
    install -d -m 0700 -o ubuntu -g ubuntu /tmp/runtime-ubuntu
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    x11-xserver-utils xclip && rm -rf /var/lib/apt/lists/*
