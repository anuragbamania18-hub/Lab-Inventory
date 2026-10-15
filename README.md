
# Laboratory Chemical Inventory System

A beginner-friendly Python Flask website for the DSA course project.

## What this version does

- Manager and attendee login
- Add chemicals manually
- Import a CSV dataset
- Generate QR codes for each chemical
- Scan/open a QR URL to view the chemical description
- Borrow/return workflow
- Record new weight on return
- Block attendee borrowing of Dangerous/Hazardous chemicals
- Low-stock alert below 20% of maximum capacity
- Manager alert resolution
- Manager undo of the latest transaction
- DSA structures in Python:
  - Hash table: dictionary for average O(1) QR/barcode lookup
  - AVL tree: ordered chemical catalog
  - Queue: low-stock alert concept
  - Stack: undo concept

## Run locally

1. Install Python 3.10+.
2. Open terminal in this folder.
3. Create a virtual environment:
   Windows:
       py -m venv venv
       venv\Scripts\activate
   macOS/Linux:
       python3 -m venv venv
       source venv/bin/activate
4. Install:
       pip install -r requirements.txt
5. Start:
       python app.py
6. Open:
       http://127.0.0.1:5000

Demo accounts:
- manager / manager123
- student / student123

## Add your dataset

Log in as manager -> Import Dataset.

CSV columns:
barcode,name,description,current_weight,max_capacity,unit,hazard,location

You can download the sample CSV from the Import Dataset page, or edit sample_dataset.csv and import it. CSV headers are matched case-insensitively; each row is validated before any records are saved.

The database and generated QR images are stored relative to the application folder, regardless of the directory used to start the server. Set DATABASE_PATH to override the database location.

## How QR linking works

The QR code does NOT store the full chemical description.

It stores a URL such as:

https://YOUR-DOMAIN/chemical/ACID001

The last part (`ACID001`) is the barcode/QR value.

When the QR is scanned:
1. The phone opens the URL.
2. Flask receives `/chemical/ACID001`.
3. The server uses `ACID001` as the lookup key.
4. The database returns the chemical record.
5. The page displays the description, weight, capacity, hazard and location.

This means changing the chemical description in the database does not require printing a new QR code, as long as the barcode value stays the same.

## IMPORTANT: local QR testing

A QR containing `http://127.0.0.1:5000/...` will work only on the same computer.

For phone scanning, use a public URL. During development you can use a tunnel such as ngrok and set:

PUBLIC_BASE_URL=https://YOUR-NGROK-URL

Then restart the app and generate the QR again.

## Hosting on Render (simple option)

1. Create a GitHub repository and upload this project.
2. Create a new Web Service on Render.
3. Connect the GitHub repository.
4. Build command:
       pip install -r requirements.txt
5. Start command:
       gunicorn app:app
6. Add environment variable:
       SECRET_KEY = a-long-random-secret
7. After Render gives you a public URL, add:
       PUBLIC_BASE_URL = https://your-service.onrender.com
8. Redeploy.
9. Import your dataset and generate QR codes.

### Database warning

This starter project uses SQLite because it is simple for a DSA project. On some cloud hosting plans, the local filesystem can be ephemeral. For a production system, move the database to a managed PostgreSQL database.

## Changing demo passwords

The demo passwords are stored in the starter code for simplicity. Before real use, replace this with password hashing and proper user management.

## Project flow

QR scan
  -> /chemical/<barcode>
  -> Flask route
  -> dictionary / SQLite lookup
  -> chemical profile

Return
  -> new weight
  -> transaction saved
  -> current weight updated
  -> if weight < 20% capacity
  -> alert created
  -> manager reviews alert

## Suggested presentation explanation

"The QR code is the identifier, not the database itself. Each QR code contains a URL whose final value is the chemical's barcode. The backend receives that value and uses it as a key to find the chemical record. Therefore the QR code remains stable while the chemical's description, weight, hazard information and location can be updated in the database."

## Security note

This is a course-project prototype, not a production chemical-safety system. For real deployment add HTTPS, hashed passwords, CSRF protection, audit logging, stronger authorization, backups and a managed database.
