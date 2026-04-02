# Vercel Deployment with Password Protection

## Quick Start

Your Visme Marketing Dashboards are now protected with password authentication.

### Default Login Credentials

- **URL**: `login.html` (or just `/`)
- **Default Password**: `visme2024`

## Changing the Password

### Step 1: Edit the Login Page

Open `login.html` and find this line (around line 152):

```javascript
const CORRECT_PASSWORD = 'visme2024'; // CHANGE THIS TO YOUR DESIRED PASSWORD
```

Replace `'visme2024'` with your desired password:

```javascript
const CORRECT_PASSWORD = 'your-new-password'; // CHANGE THIS TO YOUR DESIRED PASSWORD
```

### Step 2: Commit and Push

```bash
git add login.html
git commit -m "Update dashboard password"
git push
```

Vercel will automatically redeploy with the new password.

## How It Works

1. **Login Page** (`login.html`): Users enter their password
2. **Auth Script** (`auth.js`): Protects all pages and maintains session
3. **Session Storage**: After login, users stay logged in for 24 hours
4. **Automatic Redirect**: Unauthenticated users are redirected to login

## Deploying to Vercel

### Option A: Using Vercel Web Interface (Easiest)

1. Go to https://vercel.com/new
2. Click **"Import Git Repository"**
3. Select `visme-dashboards` from your GitHub
4. Click **"Deploy"**
5. Vercel will automatically build and deploy your dashboards

### Option B: Using Vercel CLI

```bash
npm i -g vercel
cd visme-dashboards
vercel
```

## Features

✅ **Free** - No cost, uses Vercel free tier  
✅ **Secure** - Password-protected access  
✅ **Persistent** - 24-hour session duration  
✅ **Static** - Works with pure HTML/CSS/JS  
✅ **Fast** - Global CDN distribution  
✅ **Private Repo** - GitHub repo can be private  

## Making Your Repository Private

Once deployed to Vercel, you can safely make your GitHub repo private:

1. Go to GitHub: https://github.com/mattvisme/visme-dashboards/settings
2. Under "Danger Zone", click **"Change repository visibility"**
3. Select **"Private"** and confirm
4. Your Vercel deployment continues to work without interruption

## Troubleshooting

### "Password not working"
- Make sure you're using the password exactly as set in `login.html`
- Try clearing browser cookies/local storage (Ctrl+Shift+Delete)

### "Still see GitHub Pages instead of Vercel"
- Clear your browser cache
- Check that your domain points to Vercel (if using custom domain)
- Verify deployment status at https://vercel.com (check for successful deploy)

### "Logout functionality"
Users can manually clear their session by opening browser DevTools (F12) and running:
```javascript
localStorage.removeItem('dashboard_authenticated');
```

## Next Steps

1. **Change the default password** in `login.html`
2. **Deploy to Vercel** using the steps above
3. **Make your GitHub repo private** (optional but recommended)
4. **Test the login** at your Vercel domain
5. **Share the password** with your Visme team

## Questions?

Refer to the password in `login.html` or contact your administrator.
