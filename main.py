import firebase_admin
from firebase_admin import credentials, db
import random
from datetime import datetime, time as dt_time
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import cmd
import threading

# Firebase Setup
cred = credentials.Certificate('FakeStockSim Firebase Service Account.json')  # Replace with your actual path
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://fakestocksim-default-rtdb.firebaseio.com'
})

# Initial Stock Data
stocks = {
    'John Lawyers': {'name': 'John Lawyers', 'price': 94, 'previous_price': 94, 'closing_price': 94},
    'Tidli Co': {'name': 'Tidli Co', 'price': 150, 'previous_price': 150, 'closing_price': 150},
    'UMAE': {'name': 'UMAE', 'price': 500, 'previous_price': 500, 'closing_price': 500}
}

eevents = {
    'John Lawyers': [
        "launches strategic advertising campaign (+15%)",
        "experiences critical equipment failure (-20%)",
        "enters strategic partnership with Tesla (+25%)",
        "secures victory in high-profile litigation (+30%)",
        "suffers reputational damage from data breach (-40%)",
        "completes merger with major competitor (+50%)"
    ],
    'Tidli Co': [
        "successfully enters Tokyo market (+10%)",
        "issues mass product recall due to safety concerns (-25%)",
        "receives international environmental excellence award (+15%)",
        "unveils groundbreaking product innovation (+40%)",
        "faces leadership uncertainty after CEO resignation (-30%)",
        "awarded high-value government infrastructure contract (+60%)"
    ],
    'UMAE': [
        "launches Tokyo-based operations (+12%)",
        "announces voluntary recall following product flaw (-22%)",
        "recognized for sustainability innovation (+18%)",
        "reveals breakthrough in renewable energy technology (+80%)",
        "undergoes regulatory scrutiny amid compliance concerns (-45%)",
        "forms alliance with SpaceX for joint development (+70%)"
    ]
}


# Special event probabilities and impacts
special_events = {
    'John Lawyers': {
        'probability': 0.05,  # 5% chance per update
        'impacts': {
            'wins major lawsuit': 0.30,  # +30%
            'data breach scandal': -0.40,  # -40%
            'merges with rival firm': 0.50  # +50%
        }
    },
    'Tidli Co': {
        'probability': 0.05,
        'impacts': {
            'launches revolutionary product': 0.40,
            'CEO resigns': -0.30,
            'secures government contract': 0.60
        }
    },
    'UMAE': {
        'probability': 0.05,
        'impacts': {
            'discovers new energy source': 0.80,
            'regulatory investigation': -0.45,
            'partners with SpaceX': 0.70
        }
    }
}

# User Management
users = {}

# Market status
market_open = True

def get_dow_previous_close():
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EDJI?range=1d&interval=1d"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
        }

        # Set up a session with retry strategy
        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[502, 503, 504])
        session.mount('https://', HTTPAdapter(max_retries=retries))

        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        meta = data["chart"]["result"][0]["meta"]
        return meta["chartPreviousClose"]

    except Exception as e:
        # Silent error handling
        return 35000  # fallback


def market_open_now():
    now = datetime.now().time()
    return dt_time(9, 0) <= now <= dt_time(16, 0)

def calculate_percent_change(old_price, new_price):
    """Calculate percentage change with + or - sign"""
    if old_price == 0:
        return "+0.00%"
    
    percent_change = ((new_price - old_price) / old_price) * 100
    sign = "+" if percent_change >= 0 else ""
    return f"{sign}{percent_change:.2f}%"

def update_stocks():
    if not market_open:
        return  # Don't update prices if market is closed
        
    dow_reference = get_dow_previous_close()

    for comp in stocks:
        old_price = stocks[comp]['price']
        stocks[comp]['previous_price'] = old_price

        # Check for special event
        if random.random() < special_events[comp]['probability']:
            event = random.choice(list(special_events[comp]['impacts'].keys()))
            impact = special_events[comp]['impacts'][event]
            price_change = old_price * impact
            new_price = round(old_price + price_change, 2)
            
            # Log the special event
            event_text = f"SPECIAL EVENT: {comp} {event} ({'+' if impact > 0 else ''}{impact*100:.0f}%)"
            db.reference(f'events/{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}').set(event_text)
            
        else:
            # Regular market movement
            base_change = random.uniform(-0.2, 0.2)
            dow_factor = random.uniform(0.9, 1.1)
            price_change = old_price * (base_change / 100) * dow_factor
            new_price = round(old_price + price_change, 2)

        # Ensure price stays positive
        new_price = max(1, new_price)

        # Update in local dict
        stocks[comp]['price'] = new_price
        
        # Calculate percentage change
        percent_change = calculate_percent_change(old_price, new_price)

        # Firebase-safe company name
        safe_name = comp.replace(" ", "_").replace(".", "")

        # Push to Firebase
        db.reference(f'stocks/{safe_name}').set({
            'name': comp,
            'price': str(new_price),
            'change': percent_change,
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

def load_users_from_firebase():
    """Load existing users from Firebase"""
    users_ref = db.reference('users')
    users_data = users_ref.get()
    if users_data:
        # Ensure all users have required fields
        for username, user_data in users_data.items():
            if 'portfolio' not in user_data:
                user_data['portfolio'] = {}
            if 'transactions' not in user_data:
                user_data['transactions'] = []
            if 'cash' not in user_data:
                user_data['cash'] = 0.0
        return users_data
    return {}

def save_user_to_firebase(username, user_data):
    """Save a user and their investment data to Firebase"""
    # Ensure user data has all required fields
    if 'portfolio' not in user_data:
        user_data['portfolio'] = {}
    if 'transactions' not in user_data:
        user_data['transactions'] = []
    if 'cash' not in user_data:
        user_data['cash'] = 0.0
    
    # Calculate total portfolio value using current prices
    portfolio_value = 0
    formatted_portfolio = {}
    for stock, qty in user_data['portfolio'].items():
        current_price = get_stock_price(stock)
        if current_price is not None:
            stock_value = current_price * qty
            portfolio_value += stock_value
            formatted_portfolio[stock] = {
                'quantity': qty,
                'current_price': current_price,
                'total_value': stock_value
            }

    total_value = user_data['cash'] + portfolio_value

    # Create the user data structure
    firebase_data = {
        'username': username,
        'cash_balance': user_data['cash'],
        'portfolio': formatted_portfolio,
        'total_portfolio_value': total_value,
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'transactions': user_data['transactions']  # Keep transaction history
    }
        
    db.reference(f'users/{username}').set(firebase_data)

def get_stock_price(stock_name):
    """Get current price of a stock"""
    if stock_name in stocks:
        return stocks[stock_name]['price']
    return None

class StockConsole(cmd.Cmd):
    """Interactive stock trading console"""
    
    prompt = '📈 StockSim> '
    intro = """
    ===========================================
    🏦 FakeStockSim - Stock Trading Simulator 🏦
    ===========================================
    
    Type 'help' to see available commands.
    """
    
    def __init__(self):
        super().__init__()
        self.current_user = None
        
    def do_create_user(self, arg):
        """Create a new user: create_user <username> <starting_cash>"""
        args = arg.split()
        if len(args) != 2:
            print("❌ Usage: create_user <username> <starting_cash>")
            return
            
        username = args[0]
        try:
            cash = float(args[1])
        except ValueError:
            print("❌ Cash amount must be a number")
            return
            
        if username in users:
            print(f"❌ User {username} already exists!")
            return
            
        # Initialize with all required fields
        users[username] = {
            'cash': cash,
            'portfolio': {},
            'transactions': []
        }
        
        save_user_to_firebase(username, users[username])
        print(f"✅ Created user {username} with ${cash:.2f}")
        
    def do_login(self, username):
        """Log in as a user: login <username>"""
        if not username:
            print("❌ Please specify a username")
            return
            
        if username not in users:
            print(f"❌ User {username} does not exist. Create it first.")
            return
        
        # Ensure user has required fields
        if 'portfolio' not in users[username]:
            users[username]['portfolio'] = {}
        if 'transactions' not in users[username]:
            users[username]['transactions'] = []
        if 'cash' not in users[username]:
            users[username]['cash'] = 0.0
            
        self.current_user = username
        print(f"✅ Logged in as {username}")
        self.prompt = f'📈 StockSim ({username})> '
        
    def do_logout(self, arg):
        """Log out of current user"""
        if not self.current_user:
            print("❌ Not logged in")
            return
            
        prev_user = self.current_user
        self.current_user = None
        self.prompt = '📈 StockSim> '
        print(f"✅ Logged out from {prev_user}")
        
    def do_list_users(self, arg):
        """List all users"""
        if not users:
            print("No users exist yet.")
            return
            
        print("\n=== Users ===")
        for username, data in users.items():
            portfolio_value = sum(
                get_stock_price(stock) * qty 
                for stock, qty in data['portfolio'].items()
                if get_stock_price(stock) is not None
            )
            total_value = data['cash'] + portfolio_value
            print(f"{username}: ${data['cash']:.2f} cash + ${portfolio_value:.2f} stocks = ${total_value:.2f}")
            
    def do_stocks(self, arg):
        """List all available stocks"""
        print("\n=== Available Stocks ===")
        for name, data in stocks.items():
            print(f"{name}: ${data['price']:.2f}")
        print()
            
    def do_buy(self, arg):
        """Buy stocks: buy <stock_name> <quantity>"""
        if not self.current_user:
            print("❌ You must log in first")
            return
            
        args = arg.split()
        if len(args) < 2:
            print("❌ Usage: buy <stock_name> <quantity>")
            return
            
        stock_name = args[0]
        # Handle stock names with spaces
        if stock_name not in stocks and len(args) > 2:
            for i in range(1, len(args) - 1):
                test_name = " ".join(args[:i+1])
                if test_name in stocks:
                    stock_name = test_name
                    args = [stock_name] + args[i+1:]
                    break
                    
        if stock_name not in stocks:
            print(f"❌ Stock '{stock_name}' not found")
            return
            
        try:
            quantity = int(args[1])
            if quantity <= 0:
                print("❌ Quantity must be positive")
                return
        except ValueError:
            print("❌ Quantity must be a number")
            return
            
        price = stocks[stock_name]['price']
        total_cost = price * quantity
        
        # Ensure user has required fields
        if 'cash' not in users[self.current_user]:
            users[self.current_user]['cash'] = 0.0
        if 'portfolio' not in users[self.current_user]:
            users[self.current_user]['portfolio'] = {}
        if 'transactions' not in users[self.current_user]:
            users[self.current_user]['transactions'] = []
        
        if users[self.current_user]['cash'] < total_cost:
            print(f"❌ Not enough cash. Need ${total_cost:.2f}, have ${users[self.current_user]['cash']:.2f}")
            return
            
        # Update user cash
        users[self.current_user]['cash'] -= total_cost
        
        # Update portfolio
        if stock_name not in users[self.current_user]['portfolio']:
            users[self.current_user]['portfolio'][stock_name] = 0
        users[self.current_user]['portfolio'][stock_name] += quantity
        
        # Record transaction
        transaction = {
            'type': 'buy',
            'stock': stock_name,
            'quantity': quantity,
            'price': price,
            'total': total_cost,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        users[self.current_user]['transactions'].append(transaction)
        
        # Save to Firebase
        save_user_to_firebase(self.current_user, users[self.current_user])
        
        print(f"✅ Bought {quantity} shares of {stock_name} at ${price:.2f} each. Total: ${total_cost:.2f}")
        
    def do_sell(self, arg):
        """Sell stocks: sell <stock_name> <quantity>"""
        if not self.current_user:
            print("❌ You must log in first")
            return
            
        args = arg.split()
        if len(args) < 2:
            print("❌ Usage: sell <stock_name> <quantity>")
            return
            
        stock_name = args[0]
        # Handle stock names with spaces
        if stock_name not in stocks and len(args) > 2:
            for i in range(1, len(args) - 1):
                test_name = " ".join(args[:i+1])
                if test_name in stocks:
                    stock_name = test_name
                    args = [stock_name] + args[i+1:]
                    break
                    
        if stock_name not in stocks:
            print(f"❌ Stock '{stock_name}' not found")
            return
            
        try:
            quantity = int(args[1])
            if quantity <= 0:
                print("❌ Quantity must be positive")
                return
        except ValueError:
            print("❌ Quantity must be a number")
            return
        
        # Ensure user has required fields
        if 'portfolio' not in users[self.current_user]:
            users[self.current_user]['portfolio'] = {}
        if 'transactions' not in users[self.current_user]:
            users[self.current_user]['transactions'] = []
        if 'cash' not in users[self.current_user]:
            users[self.current_user]['cash'] = 0.0
            
        # Check if user has enough shares
        if stock_name not in users[self.current_user]['portfolio'] or users[self.current_user]['portfolio'][stock_name] < quantity:
            owned = users[self.current_user]['portfolio'].get(stock_name, 0)
            print(f"❌ Not enough shares. Want to sell {quantity}, but only have {owned}")
            return
            
        price = stocks[stock_name]['price']
        total_value = price * quantity
        
        # Update user cash
        users[self.current_user]['cash'] += total_value
        
        # Update portfolio
        users[self.current_user]['portfolio'][stock_name] -= quantity
        if users[self.current_user]['portfolio'][stock_name] == 0:
            del users[self.current_user]['portfolio'][stock_name]
        
        # Record transaction
        transaction = {
            'type': 'sell',
            'stock': stock_name,
            'quantity': quantity,
            'price': price,
            'total': total_value,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        users[self.current_user]['transactions'].append(transaction)
        
        # Save to Firebase
        save_user_to_firebase(self.current_user, users[self.current_user])
        
        print(f"✅ Sold {quantity} shares of {stock_name} at ${price:.2f} each. Total: ${total_value:.2f}")
        
    def do_portfolio(self, arg):
        """Show current user's portfolio"""
        if not self.current_user:
            print("❌ You must log in first")
            return
        
        # Ensure user has required fields
        if 'portfolio' not in users[self.current_user]:
            users[self.current_user]['portfolio'] = {}
        if 'cash' not in users[self.current_user]:
            users[self.current_user]['cash'] = 0.0
            
        user_data = users[self.current_user]
        print(f"\n=== {self.current_user}'s Portfolio ===")
        print(f"Cash: ${user_data['cash']:.2f}")
        
        if not user_data['portfolio']:
            print("No stocks owned.")
        else:
            print("\nStocks:")
            total_value = 0
            for stock, quantity in user_data['portfolio'].items():
                price = get_stock_price(stock)
                value = price * quantity
                total_value += value
                print(f"{stock}: {quantity} shares @ ${price:.2f} = ${value:.2f}")
                
            print(f"\nTotal Portfolio Value: ${user_data['cash'] + total_value:.2f}")
            
        # Save updated portfolio value to Firebase
        save_user_to_firebase(self.current_user, user_data)
        
    def do_history(self, arg):
        """Show transaction history for current user"""
        if not self.current_user:
            print("❌ You must log in first")
            return
        
        # Ensure user has required fields
        if 'transactions' not in users[self.current_user]:
            users[self.current_user]['transactions'] = []
            
        transactions = users[self.current_user]['transactions']
        if not transactions:
            print("No transaction history.")
            return
            
        print(f"\n=== {self.current_user}'s Transaction History ===")
        for i, t in enumerate(transactions):
            print(f"{i+1}. {t['timestamp']} - {t['type'].upper()} {t['quantity']} {t['stock']} @ ${t['price']:.2f} = ${t['total']:.2f}")
            
    def do_exit(self, arg):
        """Exit the program"""
        print("Thank you for using FakeStockSim!")
        return True
        
    def do_quit(self, arg):
        """Exit the program"""
        return self.do_exit(arg)

    def do_market_status(self, arg):
        """Show current market status"""
        status = "OPEN" if market_open else "CLOSED"
        print(f"\n=== Market Status ===")
        print(f"Market is currently {status}")
        if not market_open:
            print("\nClosing Prices:")
            for name, data in stocks.items():
                print(f"{name}: ${data['closing_price']:.2f}")
        print()
        
    def do_close_market(self, arg):
        """Close the market and save closing prices"""
        global market_open
        if not market_open:
            print("❌ Market is already closed")
            return
            
        print("\n=== Closing Market ===")
        for comp in stocks:
            # Save current price as closing price
            stocks[comp]['closing_price'] = stocks[comp]['price']
            
            # Update Firebase with closing price and market status
            safe_name = comp.replace(" ", "_").replace(".", "")
            db.reference(f'stocks/{safe_name}').update({
                'closing_price': str(stocks[comp]['closing_price']),
                'market_status': 'closed',
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
            print(f"Saved closing price for {comp}: ${stocks[comp]['closing_price']:.2f}")
            
        # Set global market status
        market_open = False
        db.reference('market_status').set('closed')
        print("\n✅ Market is now closed")
        
    def do_open_market(self, arg):
        """Open the market"""
        global market_open
        if market_open:
            print("❌ Market is already open")
            return
            
        # Update market status in Firebase
        db.reference('market_status').set('open')
        
        # Reset previous prices to closing prices
        for comp in stocks:
            stocks[comp]['previous_price'] = stocks[comp]['closing_price']
            safe_name = comp.replace(" ", "_").replace(".", "")
            db.reference(f'stocks/{safe_name}').update({
                'previous_price': str(stocks[comp]['previous_price']),
                'market_status': 'open',
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
        
        market_open = True
        print("\n✅ Market is now open")

def main():
    # Load existing users from Firebase
    global users
    users = load_users_from_firebase()
    print(f"Loaded {len(users)} users from database")
    
    # Start the stock update in a separate thread
    update_thread = threading.Thread(target=stock_updater, daemon=True)
    update_thread.start()
    
    # Start the console
    console = StockConsole()
    try:
        console.cmdloop()
    except KeyboardInterrupt:
        print("\nExiting FakeStockSim...")

def stock_updater():
    """Background thread to update stocks"""
    print("🏦 Stock simulator running in background...")
    while True:
        try:
            if market_open and market_open_now():
                update_stocks()
            time.sleep(1)
        except Exception as e:
            # Only print serious errors
            print(f"\n🔥 Error in stock updater: {str(e)}")

if __name__ == "__main__":
    main()