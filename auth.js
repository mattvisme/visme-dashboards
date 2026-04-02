// Auth protection script - add this to the top of index.html and each dashboard HTML file
(function() {
    const SESSION_KEY = 'dashboard_authenticated';
    const SESSION_EXPIRY = 24 * 60 * 60 * 1000; // 24 hours

    function checkAuth() {
        // Don't protect login page
        if (window.location.pathname.includes('login.html')) {
            return;
        }

        const stored = localStorage.getItem(SESSION_KEY);
        
        if (!stored) {
            window.location.href = '/login.html';
            return;
        }

        try {
            const { timestamp } = JSON.parse(stored);
            const now = Date.now();
            
            // Check if session expired
            if (now - timestamp > SESSION_EXPIRY) {
                localStorage.removeItem(SESSION_KEY);
                window.location.href = '/login.html';
                return;
            }
            
            // Refresh timestamp (extend session on each visit)
            localStorage.setItem(SESSION_KEY, JSON.stringify({
                authenticated: true,
                timestamp: Date.now()
            }));
        } catch (e) {
            localStorage.removeItem(SESSION_KEY);
            window.location.href = '/login.html';
        }
    }

    // Run auth check when page loads
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', checkAuth);
    } else {
        checkAuth();
    }
})();
