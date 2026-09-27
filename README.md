# Telegram Car Lottery Bot

A Telegram bot built with Python to manage a 3,500-ticket car lottery. Features dynamic inline keyboards with role-based permissions for Admins and regular Users.

## Features

- **Public Features (All Users):**
  - **Check Number:** Look up the status of any ticket (1–3500).
  - **List Numbers:** View total, available, and reserved ticket counts.
- **Admin Features (Admins Only):**
  - **Reserve Number:** Reserve a specific available ticket.
  - **Reserved List:** View all currently reserved tickets.
  - **Lotto Status:** View real-time lottery completion metrics and dashboard.
- **Access Control:** User interface and backend routes dynamically restrict admin capabilities based on Telegram User IDs.

---

## Setup & Running

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/YOUR_USERNAME/YOUR_REPOSITORY_NAME.git](https://github.com/YOUR_USERNAME/YOUR_REPOSITORY_NAME.git)
   cd YOUR_REPOSITORY_NAME
