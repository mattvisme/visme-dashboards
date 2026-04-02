// Auth protection script - add this to the top of index.html and each dashboard HTML file
(function() {
    const SESSION_KEY = 'dashboard_authenticated';
    const SESSION_EXPIRY = 24 * 60 * 60 * 1000; // 24 hours

    function checkAuth() {
        // Don't protect login page
        if (window.location.pathname.includes('login.html') || window.location.href.includes('login.html')) {
            return;
        }

        const stored = localStorage.getItem(SESSION_KEY);
        
        if (!stored) {
            // No session, redirect to login
            window.location.replace('/login.html');
            return;
        }

        try {
            const data = JSON.parse(stored);
            const now = Date.now();
            
            // Check if session expired
            if (now - data.timestamp > SESSION_EXPIRY) {
                localStorage.removeItem(SESSION_KEY);
                window.location.replace('/login.html');
                return;
            }
            
            // Refresh timestamp (extend session on each visit)
            localStorage.setItem(SESSION_KEY, JSON.stringify({
                authenticated: true,
                timestamp: Date.now()
            }));
        } catch (e) {
            localStorage.removeItem(SESSION_KEY);
            window.location.replace('/login.html');
        }
    }

    // Run auth check IMMEDIATELY, don't wait for DOM
    checkAuth();
})();