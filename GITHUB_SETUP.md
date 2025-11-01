# GitHub Setup Instructions

## Option 1: Create a New Repository on GitHub

1. **Go to GitHub**: https://github.com/new
2. **Create Repository**:
   - Repository name: `invoice-approval-system` (or any name you prefer)
   - Description: "Intelligent invoice approval system powered by LLM"
   - Visibility: Choose Public or Private
   - **DO NOT** initialize with README, .gitignore, or license (we already have these)
   - Click "Create repository"

3. **Push your code**:
   ```bash
   git remote add origin https://github.com/aadithya1996/invoice-approval-system.git
   git branch -M main
   git push -u origin main
   ```

## Option 2: Push to Existing Repository

If you already have a repository at https://github.com/aadithya1996/expense_approval_system:

```bash
git remote add origin https://github.com/aadithya1996/expense_approval_system.git
git branch -M main
git push -u origin main
```

## Alternative: Using SSH (if you have SSH keys set up)

```bash
git remote add origin git@github.com:aadithya1996/invoice-approval-system.git
git branch -M main
git push -u origin main
```

## What's Already Done ✅

- ✅ Git initialized
- ✅ Git user configured (aadithya1996 / aadithya1996@gmail.com)
- ✅ .gitignore created (excludes .env, *.db, lib/, etc.)
- ✅ All files staged and committed
- ✅ Initial commit created

## Next Steps

1. Create the repository on GitHub (or use existing)
2. Run the push commands above
3. Your code will be on GitHub!

## Troubleshooting

**If you get "remote origin already exists":**
```bash
git remote remove origin
git remote add origin https://github.com/aadithya1996/YOUR-REPO-NAME.git
```

**If you get authentication errors:**
- Use GitHub Personal Access Token instead of password
- Or set up SSH keys: https://docs.github.com/en/authentication/connecting-to-github-with-ssh

