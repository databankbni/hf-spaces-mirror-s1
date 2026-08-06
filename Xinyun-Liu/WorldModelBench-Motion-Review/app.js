const videos = [
  {
    id: 1,
    title: "Physics-IQ: ball and rotating paper",
    prompt: "The ball moves downward while the paper board rotates.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "01_physics_iq_ball_and_rotating_paper.mp4",
  },
  {
    id: 2,
    title: "Panda-70M: freeway interchange at dusk",
    prompt: "An aerial view of a freeway intersection at the dusk.",
    frame: "3 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "02_panda_freeway_interchange_dusk.mp4",
  },
  {
    id: 3,
    title: "Panda-70M: hug in front of trophy",
    prompt: "Two men hugging each other in front of a trophy.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "03_panda_hug_in_front_of_trophy.mp4",
  },
  {
    id: 4,
    title: "HAD test0053: turn right",
    prompt: "Turn right at the intersection.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "04_had_test0053_turn_right.mp4",
  },
  {
    id: 5,
    title: "HAD test0053: follow traffic rules",
    prompt: "The vehicle proceeds according to traffic rules.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "05_had_test0053_follow_traffic_rules.mp4",
  },
  {
    id: 6,
    title: "Sekai: look up at the ceiling",
    prompt: "The person looks up at the ceiling.",
    frame: "14 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "06_sekai_look_up_at_ceiling.mp4",
  },
  {
    id: 7,
    title: "WISA-80K: ascending drone",
    prompt: "A view from an ascending drone.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "07_wisa_ascending_drone.mp4",
  },
  {
    id: 8,
    title: "PAI Transfer: robot hands over milk tea",
    prompt: "The robot hands the milk tea to the woman.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "08_pai_robot_hands_milk_tea.mp4",
  },
  {
    id: 9,
    title: "PAI Understanding: phone while driving",
    prompt: "The man talks on the phone while driving.",
    frame: "0 s",
    model: "Kling O3 Standard fallback",
    family: "kling",
    file: "09_pai_man_talks_on_phone_while_driving_kling_fallback.mp4",
  },
  {
    id: 10,
    title: "PAI Transfer: faster car and motorcycle",
    prompt: "You are driving on the road; the red car and the motorcycle are moving faster than you.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "10_pai_faster_red_car_and_motorcycle.mp4",
  },
  {
    id: 11,
    title: "Panda-70M: driver turns around cones",
    prompt: "The driver is turning around cones.",
    frame: "7 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "11_panda_driver_turns_around_cones.mp4",
  },
  {
    id: 12,
    title: "PAI Understanding: camera circles left",
    prompt: "The woman is holding a camera and moving around to her left while filming.",
    frame: "3 s",
    model: "Kling O3 Standard fallback",
    family: "kling",
    file: "12_pai_woman_circles_left_while_filming_kling_fallback.mp4",
  },
  {
    id: 13,
    title: "Panda-70M: green player spikes",
    prompt: "The player in green scores by spiking the volleyball.",
    frame: "5 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "13_panda_green_player_spikes_volleyball.mp4",
  },
  {
    id: 14,
    title: "Panda-70M: lipstick application",
    prompt: "The makeup artist is applying lipstick to the woman.",
    frame: "0 s",
    model: "Kling O3 Standard fallback",
    family: "kling",
    file: "14_panda_makeup_artist_applies_lipstick_kling_fallback.mp4",
  },
  {
    id: 27,
    label: "15",
    poster: "s15",
    title: "VGenST-Bench: cat crosses the billiard table",
    prompt: "The camera remains stationary. Within the 5-second clip, the cat moves to the opposite side of the billiard table.",
    frame: "2 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "15_vgenst_cat_opposite_side_of_billiard_table.mp4",
  },
  {
    id: 28,
    label: "16",
    poster: "s16",
    title: "VGenST-Bench: apples into and out of a box",
    prompt: "The camera remains stationary. Within the 5-second clip, the person places the two apples into the box one after the other, then removes the first apple from the box.",
    frame: "1 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "16_vgenst_two_apples_into_box_then_first_out.mp4",
  },
  {
    id: 29,
    label: "17",
    poster: "s17",
    title: "VGenST-Bench: dog crosses in front of e-bike",
    prompt: "The camera follows the electric scooter. Within the 5-second clip, a dog emerges from behind the blue Tourist Information Kiosk and crosses the road, forcing the electric scooter to slow down and yield.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "17_vgenst_dog_crosses_and_ebike_yields.mp4",
  },
  {
    id: 30,
    label: "18",
    poster: "s18",
    title: "VGenST-Bench: book opposite cup on mantel",
    prompt: "The camera remains stationary. Within the 5-second clip, the person moves the book onto the fireplace mantel and places it directly opposite the cup from the camera's perspective.",
    frame: "1 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "18_vgenst_book_opposite_cup_on_mantel.mp4",
  },
  {
    id: 31,
    label: "19",
    poster: "s19",
    title: "VGenST-Bench: reveal three container contents",
    prompt: "From left to right from the camera's perspective, the containers hold Black Ink, Gold Coins, and Rolled Parchment, respectively. Within the 5-second clip, the camera changes its viewing angle to clearly reveal the items inside all three containers.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "19_vgenst_reveal_contents_of_three_containers.mp4",
  },
  {
    id: 32,
    label: "20",
    poster: "s20",
    title: "VGenST-Bench: loop along the left wall",
    prompt: "Within the 5-second clip, the camera travels along the left wall, completes a full loop, returns to its starting position, and finishes facing the same direction as at the beginning.",
    frame: "0 s",
    model: "Seedance 2.0 Standard",
    family: "seedance",
    file: "20_vgenst_loop_along_left_wall_return_to_start.mp4",
  },
  {
    id: 15,
    label: "K01",
    poster: "k01",
    title: "Physics-IQ: ball and rotating paper",
    prompt: "The ball moves downward while the paper board rotates.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "01_physics_iq_ball_and_rotating_paper_kling.mp4",
  },
  {
    id: 16,
    label: "K02",
    poster: "k02",
    title: "Panda-70M: freeway interchange at dusk",
    prompt: "An aerial view of a freeway intersection at the dusk.",
    frame: "3 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "02_panda_freeway_interchange_dusk_kling.mp4",
  },
  {
    id: 17,
    label: "K03",
    poster: "k03",
    title: "Panda-70M: hug in front of trophy",
    prompt: "Two men hugging each other in front of a trophy.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "03_panda_hug_in_front_of_trophy_kling.mp4",
  },
  {
    id: 18,
    label: "K04",
    poster: "k04",
    title: "HAD test0053: turn right",
    prompt: "Turn right at the intersection.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "04_had_test0053_turn_right_kling.mp4",
  },
  {
    id: 19,
    label: "K05",
    poster: "k05",
    title: "HAD test0053: follow traffic rules",
    prompt: "The vehicle proceeds according to traffic rules.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "05_had_test0053_follow_traffic_rules_kling.mp4",
  },
  {
    id: 26,
    label: "K04-R",
    poster: "k04r",
    title: "HAD test0053: turn right",
    prompt: "Within the 5-second clip, the ego vehicle approaches the intersection, completes a full right turn onto the cross street, and continues straight for the remainder of the clip.",
    frame: "0 s",
    model: "Kling O3 Standard revision",
    family: "kling",
    file: "04_had_test0053_turn_right_kling_revision.mp4",
  },
  {
    id: 20,
    label: "K06",
    poster: "k06",
    title: "Sekai: look up at the ceiling",
    prompt: "The person looks up at the ceiling.",
    frame: "14 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "06_sekai_look_up_at_ceiling_kling.mp4",
  },
  {
    id: 21,
    label: "K07",
    poster: "k07",
    title: "WISA-80K: ascending drone",
    prompt: "A view from an ascending drone.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "07_wisa_ascending_drone_kling.mp4",
  },
  {
    id: 22,
    label: "K08",
    poster: "k08",
    title: "PAI Transfer: robot hands over milk tea",
    prompt: "The robot hands the milk tea to the woman.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "08_pai_robot_hands_milk_tea_kling.mp4",
  },
  {
    id: 23,
    label: "K10",
    poster: "k10",
    title: "PAI Transfer: faster car and motorcycle",
    prompt: "You are driving on the road; the red car and the motorcycle are moving faster than you.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "10_pai_faster_red_car_and_motorcycle_kling.mp4",
  },
  {
    id: 24,
    label: "K11",
    poster: "k11",
    title: "Panda-70M: driver turns around cones",
    prompt: "The driver is turning around cones.",
    frame: "7 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "11_panda_driver_turns_around_cones_kling.mp4",
  },
  {
    id: 25,
    label: "K13",
    poster: "k13",
    title: "Panda-70M: green player spikes",
    prompt: "The player in green scores by spiking the volleyball.",
    frame: "5 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "13_panda_green_player_spikes_volleyball_kling.mp4",
  },
  {
    id: 33,
    label: "K15",
    poster: "k15",
    title: "VGenST-Bench: cat crosses the billiard table",
    prompt: "The camera remains stationary. Within the 5-second clip, the cat moves to the opposite side of the billiard table.",
    frame: "2 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "15_vgenst_cat_opposite_side_of_billiard_table_kling.mp4",
  },
  {
    id: 34,
    label: "K16",
    poster: "k16",
    title: "VGenST-Bench: apples into and out of a box",
    prompt: "The camera remains stationary. Within the 5-second clip, the person places the two apples into the box one after the other, then removes the first apple from the box.",
    frame: "1 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "16_vgenst_two_apples_into_box_then_first_out_kling.mp4",
  },
  {
    id: 35,
    label: "K17",
    poster: "k17",
    title: "VGenST-Bench: dog crosses in front of e-bike",
    prompt: "The camera follows the electric scooter. Within the 5-second clip, a dog emerges from behind the blue Tourist Information Kiosk and crosses the road, forcing the electric scooter to slow down and yield.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "17_vgenst_dog_crosses_and_ebike_yields_kling.mp4",
  },
  {
    id: 36,
    label: "K18",
    poster: "k18",
    title: "VGenST-Bench: book opposite cup on mantel",
    prompt: "The camera remains stationary. Within the 5-second clip, the person moves the book onto the fireplace mantel and places it directly opposite the cup from the camera's perspective.",
    frame: "1 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "18_vgenst_book_opposite_cup_on_mantel_kling.mp4",
  },
  {
    id: 37,
    label: "K19",
    poster: "k19",
    title: "VGenST-Bench: reveal three container contents",
    prompt: "From left to right from the camera's perspective, the containers hold Black Ink, Gold Coins, and Rolled Parchment, respectively. Within the 5-second clip, the camera changes its viewing angle to clearly reveal the items inside all three containers.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "19_vgenst_reveal_contents_of_three_containers_kling.mp4",
  },
  {
    id: 38,
    label: "K20",
    poster: "k20",
    title: "VGenST-Bench: loop along the left wall",
    prompt: "Within the 5-second clip, the camera travels along the left wall, completes a full loop, returns to its starting position, and finishes facing the same direction as at the beginning.",
    frame: "0 s",
    model: "Kling O3 Standard comparison",
    family: "kling",
    file: "20_vgenst_loop_along_left_wall_return_to_start_kling.mp4",
  },
];

const gallery = document.querySelector("#gallery");
const search = document.querySelector("#search");
const filterButtons = [...document.querySelectorAll("[data-filter]")];
const emptyState = document.querySelector("#empty-state");
const viewer = document.querySelector("#viewer");
const player = document.querySelector("#video-player");
const viewerIndex = document.querySelector("#viewer-index");
const viewerTitle = document.querySelector("#viewer-title");
const viewerPrompt = document.querySelector("#viewer-prompt");
const viewerModel = document.querySelector("#viewer-model");
const viewerFrame = document.querySelector("#viewer-frame");
const closeViewer = document.querySelector("#close-viewer");
const previousVideo = document.querySelector("#previous-video");
const nextVideo = document.querySelector("#next-video");

let activeFilter = "all";
let visibleVideos = [...videos];
let currentIndex = 0;

function numberLabel(id) {
  return String(id).padStart(2, "0");
}

function displayLabel(video) {
  return video.label || numberLabel(video.id);
}

function posterKey(video) {
  return video.poster || numberLabel(video.id);
}

function renderGallery() {
  const query = search.value.trim().toLowerCase();
  visibleVideos = videos.filter((video) => {
    const modelMatch = activeFilter === "all" || video.family === activeFilter;
    const text = `${video.title} ${video.prompt} ${video.model}`.toLowerCase();
    return modelMatch && (!query || text.includes(query));
  });

  gallery.innerHTML = visibleVideos
    .map(
      (video, index) => `
        <article class="video-card">
          <button class="media-launch" type="button" data-video-index="${index}" aria-label="Play ${video.title} - ${video.model}">
            <img src="posters/${posterKey(video)}.png" alt="" width="640" height="360" loading="lazy" />
            <span class="card-number">${displayLabel(video)}</span>
            <span class="play-mark" aria-hidden="true">&#9654;</span>
          </button>
          <div class="card-content">
            <div class="card-heading">
              <h2>${video.title}</h2>
              <span class="model-badge ${video.family}">${video.family === "seedance" ? "Seedance" : "Kling"}</span>
            </div>
            <p class="card-prompt">${video.prompt}</p>
            <div class="card-meta">
              <span>Frame ${video.frame}</span>
              <span>5.04 s</span>
            </div>
          </div>
        </article>
      `,
    )
    .join("");

  emptyState.hidden = visibleVideos.length !== 0;
}

function showVideo(index) {
  if (!visibleVideos.length) return;
  currentIndex = (index + visibleVideos.length) % visibleVideos.length;
  const video = visibleVideos[currentIndex];
  viewerIndex.textContent = `Output ${displayLabel(video)} of ${videos.length}`;
  viewerTitle.textContent = video.title;
  viewerPrompt.textContent = video.prompt;
  viewerModel.textContent = video.model;
  viewerFrame.textContent = video.frame;
  player.poster = `posters/${posterKey(video)}.png`;
  player.src = `videos/${video.file}`;
  if (!viewer.open) viewer.showModal();
  player.play().catch(() => {});
}

function hideViewer() {
  player.pause();
  player.removeAttribute("src");
  player.load();
  viewer.close();
}

gallery.addEventListener("click", (event) => {
  const button = event.target.closest("[data-video-index]");
  if (button) showVideo(Number(button.dataset.videoIndex));
});

search.addEventListener("input", renderGallery);

filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activeFilter = button.dataset.filter;
    filterButtons.forEach((candidate) => candidate.classList.toggle("active", candidate === button));
    renderGallery();
  });
});

closeViewer.addEventListener("click", hideViewer);
previousVideo.addEventListener("click", () => showVideo(currentIndex - 1));
nextVideo.addEventListener("click", () => showVideo(currentIndex + 1));

viewer.addEventListener("click", (event) => {
  if (event.target === viewer) hideViewer();
});

viewer.addEventListener("cancel", (event) => {
  event.preventDefault();
  hideViewer();
});

document.addEventListener("keydown", (event) => {
  if (!viewer.open) return;
  if (event.key === "ArrowLeft") showVideo(currentIndex - 1);
  if (event.key === "ArrowRight") showVideo(currentIndex + 1);
});

renderGallery();
