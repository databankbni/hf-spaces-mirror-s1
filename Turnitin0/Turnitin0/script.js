(function () {
	"use strict";

	function setupCarousel(root) {
		const track = root.querySelector(".carousel__track");
		const prev = root.querySelector(".carousel__nav--prev");
		const next = root.querySelector(".carousel__nav--next");
		if (!track || !prev || !next) return;

		function updateNav() {
			const maxScroll = track.scrollWidth - track.clientWidth;
			const overflow = maxScroll > 4;
			prev.hidden = !overflow;
			next.hidden = !overflow;
			if (!overflow) return;
			prev.disabled = track.scrollLeft <= 4;
			next.disabled = track.scrollLeft >= maxScroll - 4;
			prev.style.opacity = prev.disabled ? "0.35" : "1";
			next.style.opacity = next.disabled ? "0.35" : "1";
		}

		function scrollByPage(direction) {
			const amount = Math.max(track.clientWidth * 0.8, 200);
			track.scrollBy({ left: direction * amount, behavior: "smooth" });
		}

		prev.addEventListener("click", function () {
			scrollByPage(-1);
		});
		next.addEventListener("click", function () {
			scrollByPage(1);
		});
		track.addEventListener("scroll", updateNav, { passive: true });
		window.addEventListener("resize", updateNav);
		if (typeof ResizeObserver !== "undefined") {
			new ResizeObserver(updateNav).observe(track);
		}
		updateNav();
	}

	document.querySelectorAll("[data-carousel]").forEach(setupCarousel);

	const lightbox = document.getElementById("lightbox");
	const lightboxImg = lightbox && lightbox.querySelector(".lightbox__img");

	function openLightbox(src, alt) {
		if (!lightbox || !lightboxImg) return;
		lightboxImg.src = src;
		lightboxImg.alt = alt || "";
		lightbox.hidden = false;
		document.body.style.overflow = "hidden";
	}

	function closeLightbox() {
		if (!lightbox || !lightboxImg) return;
		lightbox.hidden = true;
		lightboxImg.removeAttribute("src");
		lightboxImg.alt = "";
		document.body.style.overflow = "";
	}

	document.querySelectorAll("[data-lightbox-src]").forEach(function (btn) {
		btn.addEventListener("click", function () {
			openLightbox(btn.getAttribute("data-lightbox-src"), btn.getAttribute("data-lightbox-alt"));
		});
	});

	if (lightbox) {
		lightbox.addEventListener("click", function (event) {
			// Close when clicking anywhere except the enlarged image itself.
			if (event.target !== lightboxImg) {
				closeLightbox();
			}
		});
	}

	document.addEventListener("keydown", function (event) {
		if (event.key === "Escape" && lightbox && !lightbox.hidden) {
			closeLightbox();
		}
	});
})();
