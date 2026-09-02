const video = document.getElementById('videoElement');
const canvas = document.getElementById('outputCanvas');
const ctx = canvas.getContext('2d');

// Camera Start
navigator.mediaDevices.getUserMedia({ video: true })
    .then(stream => {
        video.srcObject = stream;
        video.play();
        requestAnimationFrame(processVideo);
    })
    .catch(err => {
        alert("Camera Error: Please allow camera permissions! " + err);
    });

async function processVideo() {
    if (video.readyState === video.HAVE_ENOUGH_DATA) {
        // Match dimensions
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        // Draw video frame to canvas
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        // Get image data
        let imageData = canvas.toDataURL('image/jpeg', 0.5);

        try {
            // Send to Flask
            let response = await fetch('/process_frame', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ image: imageData })
            });

            let results = await response.json();

            // Draw Results
            results.forEach(res => {
                ctx.beginPath();
                ctx.lineWidth = "4";
                if (res.label === "Mask") {
                    ctx.strokeStyle = "#00ff00";
                    ctx.fillStyle = "#00ff00";
                } else {
                    ctx.strokeStyle = "#ff0000";
                    ctx.fillStyle = "#ff0000";
                }
                ctx.rect(res.x, res.y, res.w, res.h);
                ctx.stroke();

                ctx.font = "bold 20px Arial";
                ctx.fillText(res.label + " (" + res.prob + "%)", res.x, res.y - 10);
            });

        } catch (error) {
            console.log("Log:", error);
        }
    }
    // Repeat loop (slightly delayed to save bandwidth)
    setTimeout(() => {
        requestAnimationFrame(processVideo);
    }, 100); 
}