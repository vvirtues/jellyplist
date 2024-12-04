// Initialize all tooltips on the page
var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
  return new bootstrap.Tooltip(tooltipTriggerEl)
})

// Function to open the search modal and trigger the search automatically
function openSearchModal(trackTitle, provider_track_id) {
  const modal = new bootstrap.Modal(document.getElementById('searchModal'));
  const searchQueryInput = document.getElementById('search-query');
  const providerTrackIdInput = document.getElementById('provider-track-id');

  // Pre-fill the input fields
  searchQueryInput.value = trackTitle;
  providerTrackIdInput.value = provider_track_id;

  // Show the modal
  modal.show();

  setTimeout(() => {
    searchQueryInput.form.requestSubmit(); // Trigger the form submission
  }, 200);  // Delay the search slightly to ensure the modal is visible before searching
}

let currentAudio = null;
let currentButton = null;

function playPreview(button, previewUrl) {
  
  if (currentAudio) {
    currentAudio.pause();
    if (currentButton) {
      currentButton.innerHTML = '<i class="fas fa-play"></i>';  
    }
  }

  if (currentAudio && currentAudio.src === previewUrl) {
    currentAudio = null;
    currentButton = null;
  } else {
    currentAudio = new Audio(previewUrl);
    currentAudio.play();
    currentButton = button;
    button.innerHTML = '<i class="fas fa-pause"></i>';

    currentAudio.onended = function () {
      button.innerHTML = '<i class="fas fa-play"></i>';
      currentAudio = null;
      currentButton = null;
    };
  }
}

function playJellyfinTrack(button, jellyfinId) {
  if (currentAudio && currentButton === button) {
    currentAudio.pause();
    currentAudio = null;
    currentButton.innerHTML = '<i class="fas fa-play"></i>';
    currentButton = null;
    return;
  }

  if (currentAudio) {
    currentAudio.pause();
    if (currentButton) {
      currentButton.innerHTML = '<i class="fas fa-play"></i>';
    }
  }

  fetch(`/get_jellyfin_stream/${jellyfinId}`)
    .then(response => response.json())
    .then(data => {
      const streamUrl = data.stream_url;
      currentAudio = new Audio(streamUrl);
      currentAudio.play();
      currentButton = button;
      button.innerHTML = '<i class="fas fa-stop"></i>';

      currentAudio.onended = function () {
        button.innerHTML = '<i class="fas fa-play"></i>';
        currentAudio = null;
        currentButton = null;
      };
    })
    .catch(error => console.error('Error fetching Jellyfin stream URL:', error));
}

function handleJellyfinClick(event, jellyfinId, trackTitle, providerTrackId) {
  if (event.ctrlKey) {
      // CTRL key is pressed, open the search modal
      openSearchModal(trackTitle, providerTrackId);
  } else {
      // CTRL key is not pressed, play the track
      playJellyfinTrack(event.target, jellyfinId);
  }
}