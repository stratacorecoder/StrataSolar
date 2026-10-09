window.addEventListener('DOMContentLoaded', event => {

    const sidebarToggle = document.body.querySelector('#sidebarToggle');
    if (sidebarToggle) {
        sidebarToggle.setAttribute('aria-expanded', 'false');
        sidebarToggle.addEventListener('click', event => {
            event.preventDefault();
            document.body.classList.toggle('sb-sidenav-toggled');
            setSidebarExpanded(document.body.classList.contains('sb-sidenav-toggled'));
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
            closeMobileSidebar(true);
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
            closeMobileSidebar(true);
            event.preventDefault();
        }
    });
});

function isNarrowLayout() {
    return window.matchMedia('(max-width: 991.98px)').matches;
}

function setSidebarExpanded(expanded) {
    const toggle = document.getElementById('sidebarToggle');
    if (toggle) {
        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    }
}

function closeMobileSidebar(returnFocusToToggle) {
    if (!document.body.classList.contains('sb-sidenav-toggled')) {
        return;
    }
    document.body.classList.remove('sb-sidenav-toggled');
    setSidebarExpanded(false);
    if (returnFocusToToggle) {
        const toggle = document.getElementById('sidebarToggle');
        if (toggle) {
            toggle.focus();
        }
    }
}

function collapseSidebar() {
    if (isNarrowLayout()) {
        closeMobileSidebar(true);
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
