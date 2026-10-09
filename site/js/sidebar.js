window.addEventListener('DOMContentLoaded', event => {

    const sidebarToggle = document.body.querySelector('#sidebarToggle');
    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', event => {
            event.preventDefault();
            document.body.classList.toggle('sb-sidenav-toggled');
        });
    }

    const sidenavContent = document.body.querySelector('#layoutSidenav_content');
    if (sidenavContent) {
        sidenavContent.addEventListener('click', event => {
            if (!isNarrowLayout()) {
                return;
            }
            if (!document.body.classList.contains('sb-sidenav-toggled')) {
                return;
            }
            const nav = document.getElementById('layoutSidenav_nav');
            if (nav && nav.contains(event.target)) {
                return;
            }
            document.body.classList.remove('sb-sidenav-toggled');
        });
    }

    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') {
            return;
        }
        if (!isNarrowLayout()) {
            return;
        }
        if (document.body.classList.contains('sb-sidenav-toggled')) {
            document.body.classList.remove('sb-sidenav-toggled');
            event.preventDefault();
        }
    });
});

function isNarrowLayout() {
    return window.matchMedia('(max-width: 991.98px)').matches;
}

function collapseSidebar() {
    if (isNarrowLayout()) {
        document.body.classList.remove('sb-sidenav-toggled');
    }
}

function setSidebarActive(navKey) {
    document.querySelectorAll('#sidenavAccordion .nav-link[data-sidebar]').forEach(link => {
        const active = link.getAttribute('data-sidebar') === navKey;
        link.classList.toggle('active', active);
        if (active) {
            link.setAttribute('aria-current', 'page');
        } else {
            link.removeAttribute('aria-current');
        }
    });
}
