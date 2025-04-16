from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
import json
import os
import base64
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-here')

# Initialize Firebase
firebase_credentials = os.getenv('FIREBASE_CREDENTIALS')
if firebase_credentials:
    # Decode base64 credentials
    cred_json = base64.b64decode(firebase_credentials).decode('utf-8')
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
else:
    # Fallback to file-based credentials
    cred = credentials.Certificate(os.getenv('FIREBASE_CREDENTIALS_PATH', 'FakeStockSim Firebase Service Account.json'))

firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://fakestocksim-default-rtdb.firebaseio.com'
})

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, username, user_data):
        self.id = username
        self.data = user_data

def ensure_user_fields(user_data):
    """Ensure all required fields exist in user data"""
    if 'portfolio' not in user_data:
        user_data['portfolio'] = {}
    if 'transactions' not in user_data:
        user_data['transactions'] = []
    if 'cash_balance' not in user_data:
        user_data['cash_balance'] = 0.0
    if 'total_portfolio_value' not in user_data:
        user_data['total_portfolio_value'] = user_data['cash_balance']
    if 'last_updated' not in user_data:
        user_data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    return user_data

@login_manager.user_loader
def load_user(username):
    user_ref = db.reference(f'users/{username}')
    user_data = user_ref.get()
    if user_data:
        user_data = ensure_user_fields(user_data)
        return User(username, user_data)
    return None

@app.route('/')
def index():
    # Get current stock prices
    stocks_ref = db.reference('stocks')
    stocks = stocks_ref.get() or {}
    return render_template('index.html', stocks=stocks)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        user_ref = db.reference(f'users/{username}')
        user_data = user_ref.get()
        
        if user_data:
            user_data = ensure_user_fields(user_data)
            user = User(username, user_data)
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('User not found')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        starting_cash = float(request.form['starting_cash'])
        
        # Check if user exists
        user_ref = db.reference(f'users/{username}')
        if user_ref.get():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        # Create new user
        new_user = {
            'username': username,
            'cash_balance': starting_cash,
            'portfolio': {},
            'total_portfolio_value': starting_cash,
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'transactions': []
        }
        
        user_ref.set(new_user)
        user = User(username, new_user)
        login_user(user)
        return redirect(url_for('dashboard'))
    
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    # Get user's portfolio
    user_ref = db.reference(f'users/{current_user.id}')
    user_data = user_ref.get()
    user_data = ensure_user_fields(user_data)
    
    # Get current stock prices
    stocks_ref = db.reference('stocks')
    stocks_data = stocks_ref.get() or {}
    
    # Convert Firebase-safe names back to display format
    stocks = {}
    for firebase_name, stock_data in stocks_data.items():
        display_name = from_firebase_name(firebase_name)
        stocks[display_name] = stock_data
    
    return render_template('dashboard.html', 
                         user=user_data,
                         stocks=stocks)

def to_firebase_name(stock_name):
    """Convert stock name to Firebase-safe format"""
    return stock_name.replace(" ", "_").replace(".", "")

def from_firebase_name(firebase_name):
    """Convert Firebase-safe name back to display format"""
    return firebase_name.replace("_", " ")

@app.route('/buy', methods=['POST'])
@login_required
def buy():
    stock_name = request.form['stock_name']
    quantity = int(request.form['quantity'])
    
    # Convert to Firebase-safe name for lookup
    firebase_name = to_firebase_name(stock_name)
    
    # Get current stock price
    stocks_ref = db.reference(f'stocks/{firebase_name}')
    stock_data = stocks_ref.get()
    if not stock_data:
        flash('Stock not found')
        return redirect(url_for('dashboard'))
    
    price = float(stock_data['price'])
    total_cost = price * quantity
    
    # Get user data
    user_ref = db.reference(f'users/{current_user.id}')
    user_data = user_ref.get()
    user_data = ensure_user_fields(user_data)
    
    if user_data['cash_balance'] < total_cost:
        flash('Not enough cash')
        return redirect(url_for('dashboard'))
    
    # Update user's portfolio
    if stock_name not in user_data['portfolio']:
        user_data['portfolio'][stock_name] = {
            'quantity': 0,
            'current_price': price,
            'total_value': 0
        }
    
    user_data['portfolio'][stock_name]['quantity'] += quantity
    user_data['portfolio'][stock_name]['current_price'] = price
    user_data['portfolio'][stock_name]['total_value'] = user_data['portfolio'][stock_name]['quantity'] * price
    
    # Update cash balance
    user_data['cash_balance'] -= total_cost
    
    # Add transaction
    transaction = {
        'type': 'buy',
        'stock': stock_name,
        'quantity': quantity,
        'price': price,
        'total': total_cost,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    user_data['transactions'].append(transaction)
    
    # Update total portfolio value
    portfolio_value = sum(stock['total_value'] for stock in user_data['portfolio'].values())
    user_data['total_portfolio_value'] = user_data['cash_balance'] + portfolio_value
    user_data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Save to Firebase
    user_ref.set(user_data)
    
    flash(f'Successfully bought {quantity} shares of {stock_name}')
    return redirect(url_for('dashboard'))

@app.route('/sell', methods=['POST'])
@login_required
def sell():
    stock_name = request.form['stock_name']
    quantity = int(request.form['quantity'])
    
    # Get user data
    user_ref = db.reference(f'users/{current_user.id}')
    user_data = user_ref.get()
    user_data = ensure_user_fields(user_data)
    
    if stock_name not in user_data['portfolio'] or user_data['portfolio'][stock_name]['quantity'] < quantity:
        flash('Not enough shares')
        return redirect(url_for('dashboard'))
    
    # Convert to Firebase-safe name for lookup
    firebase_name = to_firebase_name(stock_name)
    
    # Get current stock price
    stocks_ref = db.reference(f'stocks/{firebase_name}')
    stock_data = stocks_ref.get()
    price = float(stock_data['price'])
    total_value = price * quantity
    
    # Update portfolio
    user_data['portfolio'][stock_name]['quantity'] -= quantity
    user_data['portfolio'][stock_name]['total_value'] = user_data['portfolio'][stock_name]['quantity'] * price
    
    # Remove stock if quantity is 0
    if user_data['portfolio'][stock_name]['quantity'] == 0:
        del user_data['portfolio'][stock_name]
    
    # Update cash balance
    user_data['cash_balance'] += total_value
    
    # Add transaction
    transaction = {
        'type': 'sell',
        'stock': stock_name,
        'quantity': quantity,
        'price': price,
        'total': total_value,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    user_data['transactions'].append(transaction)
    
    # Update total portfolio value
    portfolio_value = sum(stock['total_value'] for stock in user_data['portfolio'].values())
    user_data['total_portfolio_value'] = user_data['cash_balance'] + portfolio_value
    user_data['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # Save to Firebase
    user_ref.set(user_data)
    
    flash(f'Successfully sold {quantity} shares of {stock_name}')
    return redirect(url_for('dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True) 