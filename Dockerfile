FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# 1. Add Mozilla PPA and set priorities to bypass Snap
RUN apt-get update && apt-get install -y software-properties-common gnupg wget ca-certificates && \
    add-apt-repository -y ppa:mozillateam/ppa

RUN echo 'Package: firefox* \n\
Pin: release o=LP-PPA-mozillateam \n\
Pin-Priority: 1001' > /etc/apt/preferences.d/mozilla-firefox

# 2. Install everything (using Firefox from the PPA)
RUN apt-get update && apt-get install -y \
    xvfb \
    fluxbox \
    x11vnc \
    novnc \
    websockify \
    supervisor \
    firefox \
    fonts-liberation \
    libasound2 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgcc-s1 \
    libgdk-pixbuf2.0-0 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    libgbm1 \
    ca-certificates \
    lsb-release \
    unzip \
    && apt-get clean

# 2b. Create a persistent, writable profile directory for Firefox
RUN mkdir -p /tmp/firefox-profile && chmod -R 777 /tmp/firefox-profile

# 3. Enable the full noVNC interface (with fullscreen button)
RUN ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html

WORKDIR /app
COPY . .

# Fix permissions
RUN chmod -R 777 /tmp
RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
