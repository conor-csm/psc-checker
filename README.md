# PSC Checker

A web tool for checking UK Companies House PSC (Person with Significant Control) ownership data.

## Deploying to Railway

1. Push this folder to a GitHub repository
2. Go to railway.app and sign up / log in
3. Click "New Project" → "Deploy from GitHub repo"
4. Select this repository
5. Once deployed, go to your project → Variables → Add:
   - Key: `CH_API_KEY`
   - Value: your Companies House API key
6. Railway will automatically redeploy — your tool is live!

## Local Development

```bash
pip install -r requirements.txt
CH_API_KEY=your_key_here python app.py
```

Then open http://localhost:5000
