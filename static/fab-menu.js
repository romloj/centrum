// FAB Menu
document.addEventListener('DOMContentLoaded', function() {
    const fabContainer = document.getElementById('fabContainer');
    const fabMainBtn = document.getElementById('fabMainBtn');
    const fabBackdrop = document.getElementById('fabBackdrop');

    if (fabMainBtn) {
        fabMainBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            fabContainer.classList.toggle('open');
        });
    }

    if (fabBackdrop) {
        fabBackdrop.addEventListener('click', () => {
            fabContainer.classList.remove('open');
        });
    }

    // Zamknij menu po kliknięciu linku
    document.querySelectorAll('.fab-button').forEach(btn => {
        btn.addEventListener('click', () => {
            fabContainer.classList.remove('open');
        });
    });

    // Zamknij menu klawiszem ESC
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && fabContainer.classList.contains('open')) {
            fabContainer.classList.remove('open');
        }
    });
});