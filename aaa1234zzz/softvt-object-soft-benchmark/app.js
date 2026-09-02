const cameraButtons = [...document.querySelectorAll("[data-camera-src]")];
const cameraVideo = document.querySelector("#native-camera-video");
const cameraSource = document.querySelector("#native-camera-source");
const cameraLabel = document.querySelector("#native-camera-label");
const cameraDetail = document.querySelector("#native-camera-detail");
const cameraDownload = document.querySelector("#native-camera-download");

for (const button of cameraButtons) {
  button.addEventListener("click", () => {
    if (button.getAttribute("aria-pressed") === "true") return;

    cameraVideo.pause();
    for (const candidate of cameraButtons) {
      const selected = candidate === button;
      candidate.classList.toggle("active", selected);
      candidate.setAttribute("aria-pressed", String(selected));
    }

    const source = button.dataset.cameraSrc;
    cameraSource.src = source;
    cameraVideo.poster = button.dataset.cameraPoster;
    cameraVideo.load();
    cameraLabel.textContent = button.dataset.cameraLabel;
    cameraDetail.textContent = button.dataset.cameraDetail;
    cameraDownload.href = source;
    cameraDownload.download = source;
    cameraDownload.textContent = `Download ${button.textContent.trim().toLowerCase()}`;
  });
}

function bindSynchronizedVideos(videoSelector, playSelector, pauseSelector) {
  const videos = [...document.querySelectorAll(videoSelector)];
  let groupAction = false;

  async function playTogether(startTime) {
    if (groupAction) return;
    groupAction = true;
    try {
      for (const video of videos) {
        video.currentTime = startTime;
      }
      await Promise.allSettled(videos.map((video) => video.play()));
    } finally {
      groupAction = false;
    }
  }

  function pauseTogether() {
    if (groupAction) return;
    groupAction = true;
    for (const video of videos) {
      video.pause();
    }
    groupAction = false;
  }

  document.querySelector(playSelector)?.addEventListener("click", () => {
    void playTogether(0);
  });

  document.querySelector(pauseSelector)?.addEventListener("click", pauseTogether);

  for (const sourceVideo of videos) {
    sourceVideo.addEventListener("play", () => {
      if (!groupAction) void playTogether(sourceVideo.currentTime);
    });
    sourceVideo.addEventListener("pause", () => {
      if (!sourceVideo.ended) pauseTogether();
    });
  }
}

bindSynchronizedVideos("[data-sync-rollout]", "#play-native-rollout", "#pause-native-rollout");
bindSynchronizedVideos("[data-sync-tacex]", "#play-tacex-rollout", "#pause-tacex-rollout");
