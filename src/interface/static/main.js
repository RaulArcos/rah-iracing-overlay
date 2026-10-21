document.addEventListener('DOMContentLoaded', function() {
    initThemeSelector();

    fetch('/get_overlays')
        .then(response => response.json())
        .then(overlays => {
            const overlayList = document.getElementById('overlayList');
            overlays.forEach(overlay => {
                const displayName = overlay.display_name || 'Unknown';
                const description = overlay.description || 'No description available.';
                const hasPosition = overlay.position != null;
                const folderName = overlay.folder_name;
                const dpiInfo = overlay.dpi_info || {scale: 1.0};
                const previewGif = overlay.preview_gif || '/images/default-preview.gif';

                // Store the overlay properties in localStorage for later use
                if (overlay.position) {
                    localStorage.setItem(`overlay_position_${folderName}`, JSON.stringify(overlay.position));
                }

                const cardDiv = document.createElement('div');
                cardDiv.className = 'card'; 
                cardDiv.setAttribute('data-folder', folderName);
                cardDiv.setAttribute('data-name', displayName);
                cardDiv.setAttribute('data-description', description);
                cardDiv.setAttribute('data-preview', previewGif);

                const card2Div = document.createElement('div');
                card2Div.className = 'card2';

                card2Div.innerHTML = `
                    <div class="overlay-info">
                    <h4>${displayName}</h4>
                    ${hasPosition ? `<small>Position saved: (${overlay.position.x}, ${overlay.position.y})</small>` : ''}
                    </div>
                    <div class="button-container">
                        <button id="toggle-${folderName}" class="small-button" data-status="closed" data-name="${displayName}" title="Launch/Close Overlay" data-folder="${folderName}">
                            <i class="fa-solid fa-arrow-up"></i>
                        </button>
                        <div class="secondary-buttons">
                            <button onclick="launchOverlay('${displayName}', '${folderName}', false)" title="Position Mode" class="small-button">
                                <i class="fa-solid fa-arrows-up-down-left-right"></i>
                            </button>
                        </div>
                        <button onclick="openOverlayUrl('${overlay.url}')" title="Open URL" class="small-button">
                            <i class="fa-solid fa-globe"></i>
                        </button>
                    </div>
                `;

                cardDiv.appendChild(card2Div);
                overlayList.appendChild(cardDiv);

                cardDiv.addEventListener('click', function(e) {
                    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
                        return;
                    }
                    
                    document.querySelectorAll('.card').forEach(card => card.classList.remove('active'));
                    cardDiv.classList.add('active');
                    document.querySelectorAll('.card2').forEach(card2 => card2.classList.remove('active'));
                    card2Div.classList.add('active');
                    
                    showPreview(
                        this.getAttribute('data-name'),
                        this.getAttribute('data-description'),
                        this.getAttribute('data-preview')
                    );
                });
                
                setTimeout(() => {
                    const toggleBtn = document.getElementById(`toggle-${folderName}`);
                    if (toggleBtn) {
                        toggleBtn.addEventListener('click', function() {
                            const status = this.getAttribute('data-status');
                            const name = this.getAttribute('data-name');
                            const folder = this.getAttribute('data-folder');
                            
                            if (status === 'closed') {
                                launchOverlay(name, folder, true);
                                this.setAttribute('data-status', 'open');
                                this.innerHTML = '<i class="fa-solid fa-arrow-down"></i>';
                                this.style.backgroundColor = '#e74c3c';
                                
                                localStorage.setItem(`overlay_open_${folder}`, 'true');
                            } else {
                                closeOverlay(name, folder);
                                this.setAttribute('data-status', 'closed');
                                this.innerHTML = '<i class="fa-solid fa-arrow-up"></i>';
                                this.style.backgroundColor = '#ED2727';
                                
                                localStorage.removeItem(`overlay_open_${folder}`);
                            }
                        });
                        
                        if (localStorage.getItem(`overlay_open_${folderName}`) === 'true') {
                            toggleBtn.setAttribute('data-status', 'open');
                            toggleBtn.innerHTML = '<i class="fa-solid fa-arrow-down"></i>';
                            toggleBtn.style.backgroundColor = '#e74c3c';
                        }
                    }
                }, 0);
            });
            
            syncActiveOverlays();
            
            if (overlays.length > 0) {
                const firstCard = document.querySelector('.card');
                if (firstCard) {
                    firstCard.click();
                }
            }
        });

    if (localStorage.getItem('positioning_overlay')) {
        const positioningInfo = JSON.parse(localStorage.getItem('positioning_overlay'));
        createSavePositionButton(positioningInfo.displayName, positioningInfo.folderName);
    }
});

function showPreview(name, description, previewUrl) {
    const previewContent = document.querySelector('.preview-content');
    const previewPlaceholder = document.querySelector('.preview-placeholder');
    
    document.getElementById('previewTitle').textContent = name;
    document.getElementById('previewDescription').textContent = description;
    
    const previewImg = document.getElementById('previewGif');
    const previewContainer = previewImg.parentElement;
    
    if (previewUrl) {
        previewImg.style.display = 'block';
        if (document.getElementById('noPreviewMessage')) {
            document.getElementById('noPreviewMessage').remove();
        }
        
        previewImg.src = previewUrl;
        previewImg.alt = `${name} Preview`;
        
        previewImg.onerror = function() {
            showNoPreviewMessage(previewContainer, previewImg);
        };
    } else {
        showNoPreviewMessage(previewContainer, previewImg);
    }
    
    previewPlaceholder.style.display = 'none';
    previewContent.style.display = 'flex';
}

function showNoPreviewMessage(container, imgElement) {
    imgElement.style.display = 'none';
    
    if (document.getElementById('noPreviewMessage')) {
        document.getElementById('noPreviewMessage').remove();
    }
    
    const message = document.createElement('div');
    message.id = 'noPreviewMessage';
    message.className = 'no-preview-message';
    message.innerHTML = `
        <i class="fa-solid fa-eye-slash"></i>
        <p>No preview available for this overlay</p>
    `;
    
    container.appendChild(message);
}

function syncActiveOverlays() {
    fetch('/get_active_overlays')
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const activeOverlays = data.active_overlays;
                
                document.querySelectorAll('[id^="toggle-"]').forEach(btn => {
                    const folderName = btn.getAttribute('data-folder');
                    
                    if (!activeOverlays[folderName]) {
                        btn.setAttribute('data-status', 'closed');
                        btn.innerHTML = '<i class="fa-solid fa-arrow-up"></i>';
                        btn.style.backgroundColor = '#ED2727';
                        localStorage.removeItem(`overlay_open_${folderName}`);
                    }
                });
                
                for (const [folderName, overlayInfo] of Object.entries(activeOverlays)) {
                    const toggleBtn = document.getElementById(`toggle-${folderName}`);
                    if (toggleBtn) {
                        toggleBtn.setAttribute('data-status', 'open');
                        toggleBtn.innerHTML = '<i class="fa-solid fa-arrow-down"></i>';
                        toggleBtn.style.backgroundColor = '#e74c3c';
                        localStorage.setItem(`overlay_open_${folderName}`, 'true');
                    }
                }
            }
        })
        .catch(error => {
            console.error('Error fetching active overlays:', error);
        });
}

function initThemeSelector() {
    const themeSelect = document.getElementById('themeSelect');
    if (!themeSelect || !window.RAHOverlayTheme) {
        return;
    }

    const stored = window.RAHOverlayTheme.getStored(window.localStorage);
    themeSelect.value = stored || window.RAHOverlayTheme.defaultTheme;

    themeSelect.addEventListener('change', function() {
        if (window.RAHOverlayTheme.setStored(themeSelect.value, window.localStorage)) {
            showToast(`Theme saved: ${themeSelect.value}`);
        } else {
            showToast('Could not save theme preference; it applies to this session only', true);
        }
    });
}

function getSelectedTheme() {
    const themeSelect = document.getElementById('themeSelect');
    if (window.RAHOverlayTheme && themeSelect && themeSelect.value) {
        return window.RAHOverlayTheme.apply(themeSelect.value, document.documentElement);
    }
    return window.RAHOverlayTheme ? window.RAHOverlayTheme.defaultTheme : 'original';
}

function openOverlayUrl(url) {
    window.open(`${url}?theme=${getSelectedTheme()}`, '_blank');
}

function launchOverlay(displayName, folderName, isTransparent = true) {
    fetch('/launch', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ 
            overlay: displayName,
            transparent: isTransparent,
            theme: getSelectedTheme()
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`${displayName} launched in ${isTransparent ? 'transparent' : 'positioning'} mode`);
            
            if (isTransparent) {
                localStorage.setItem(`overlay_open_${folderName}`, 'true');
                
                const toggleBtn = document.getElementById(`toggle-${folderName}`);
                if (toggleBtn) {
                    toggleBtn.setAttribute('data-status', 'open');
                    toggleBtn.innerHTML = '<i class="fa-solid fa-arrow-down"></i>';
                    toggleBtn.style.backgroundColor = '#e74c3c';
                }
            }
            
            if (!isTransparent) {
                showToast('Move overlay to desired position and click the Save Position button in the overlay window', false, 6000);
            }
        }
    })
    .catch(error => {
        console.error('Error launching overlay:', error);
        showToast('Network error launching overlay', true);
    });
}

function createSavePositionButton(displayName, folderName) {
    const existingButton = document.getElementById('savePositionButton');
    if (existingButton) {
        existingButton.remove();
    }
    
    const saveButton = document.createElement('div');
    saveButton.id = 'savePositionButton';
    saveButton.className = 'floating-save-button';
    saveButton.innerHTML = `
        <button onclick="savePositionAndToggle('${displayName}', '${folderName}')">
            <i class="fa-solid fa-floppy-disk"></i> Save Position
        </button>
    `;
    
    document.body.appendChild(saveButton);
}

function savePositionAndToggle(displayName, folderName) {
    const currentPosition = JSON.parse(localStorage.getItem(`overlay_position_${folderName}`)) || { x: 100, y: 100 };
    currentPosition.x = Math.floor(Math.random() * window.innerWidth);  
    currentPosition.y = Math.floor(Math.random() * window.innerHeight);
    
    localStorage.setItem(`overlay_position_${folderName}`, JSON.stringify(currentPosition));
    
    fetch('/toggle_to_transparent', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ 
            overlay: displayName,
            position: currentPosition
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`Position saved and transparent overlay launched at the new position (${currentPosition.x}, ${currentPosition.y})`);
            
            const saveButton = document.getElementById('savePositionButton');
            if (saveButton) {
                saveButton.remove();
            }
            
            localStorage.removeItem('positioning_overlay');
            
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast('Error saving position or toggling overlay', true);
        }
    });
}

function closeOverlay(displayName, folderName) {
    fetch('/close_overlay', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ 
            overlay: displayName,
            folder_name: folderName
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            showToast(`${displayName} closed`);
            
            localStorage.removeItem(`overlay_open_${folderName}`);
            
            const toggleBtn = document.getElementById(`toggle-${folderName}`);
            if (toggleBtn) {
                toggleBtn.setAttribute('data-status', 'closed');
                toggleBtn.innerHTML = '<i class="fa-solid fa-arrow-up"></i>';
                toggleBtn.style.backgroundColor = '#ED2727';
            }
        } else {
            showToast('Error closing overlay', true);
        }
    })
    .catch(error => {
        console.error('Error closing overlay:', error);
        showToast('Network error closing overlay', true);
    });
}

function showToast(message, isError = false, duration = 3000) {
    const existingToast = document.getElementById('toast');
    if (existingToast) {
        existingToast.remove();
    }
    
    const toast = document.createElement('div');
    toast.id = 'toast';
    toast.className = isError ? 'toast error' : 'toast';
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    setTimeout(() => toast.classList.add('show'), 100);
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 500);
    }, duration);
} 