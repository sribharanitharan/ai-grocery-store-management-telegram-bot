"""
Seed script — populates the database with real Indian kirana store products.
Run this once: python -m db.seed
"""
from db.database import engine, get_db
from db.models import Base, Product, OwnerPreference

PRODUCTS = [
    # name, sku, unit, is_loose, cost_price, mrp, qty, reorder_lvl, hsn_code, gst_slab
    ("Aashirvaad Atta 5kg",       "ATTA5KG",   "packet", False, 195.0, 220.0, 30, 10, "1101", 5.0),
    ("Aashirvaad Atta 10kg",      "ATTA10KG",  "packet", False, 380.0, 420.0, 15, 5,  "1101", 5.0),
    ("Tata Salt 1kg",             "SALT1KG",   "packet", False, 18.0,  22.0,  50, 15, "2501", 0.0),
    ("Fortune Sunflower Oil 1L",  "OIL1L",     "litre",  False, 140.0, 160.0, 25, 8,  "1512", 5.0),
    ("Fortune Sunflower Oil 5L",  "OIL5L",     "litre",  False, 680.0, 750.0, 10, 4,  "1512", 5.0),
    ("Amul Butter 100g",          "BUTTER100", "piece",  False, 48.0,  56.0,  20, 8,  "0405", 12.0),
    ("Amul Butter 500g",          "BUTTER500", "piece",  False, 220.0, 255.0, 10, 4,  "0405", 12.0),
    ("Amul Gold Milk 500ml",      "MILK500",   "packet", False, 29.0,  33.0,  30, 15, "0401", 0.0),
    ("Maggi Noodles 70g",         "MAGGI70",   "packet", False, 12.0,  14.0,  60, 20, "1902", 12.0),
    ("Maggi Noodles 70g (4pk)",   "MAGGI4PK",  "packet", False, 46.0,  56.0,  25, 10, "1902", 12.0),
    ("Parle-G 100g",              "PARLEG100", "packet", False, 9.0,   10.0,  50, 20, "1905", 5.0),
    ("Parle-G 250g",              "PARLEG250", "packet", False, 22.0,  25.0,  30, 10, "1905", 5.0),
    ("Britannia Bread (400g)",    "BREAD400",  "piece",  False, 32.0,  38.0,  15, 6,  "1905", 5.0),
    ("Good Day Cashew 60g",       "GOODDAY60", "packet", False, 18.0,  20.0,  40, 15, "1905", 5.0),
    ("Surf Excel 500g",           "SURF500",   "packet", False, 75.0,  90.0,  20, 8,  "3402", 18.0),
    ("Surf Excel 1kg",            "SURF1KG",   "packet", False, 140.0, 165.0, 12, 5,  "3402", 18.0),
    ("Ariel 500g",                "ARIEL500",  "packet", False, 78.0,  92.0,  15, 6,  "3402", 18.0),
    ("Dove Soap 75g",             "DOVE75",    "piece",  False, 38.0,  46.0,  30, 10, "3401", 18.0),
    ("Lifebuoy Soap 100g",        "LIFEBUOY",  "piece",  False, 22.0,  28.0,  40, 15, "3401", 18.0),
    ("Head & Shoulders 180ml",    "HNS180",    "piece",  False, 158.0, 185.0, 12, 5,  "3305", 18.0),
    ("Colgate 200g",              "COLGATE200","piece",  False, 68.0,  82.0,  20, 8,  "3306", 18.0),
    ("Clinic Plus Shampoo 80ml",  "CLINIC80",  "piece",  False, 58.0,  70.0,  15, 6,  "3305", 18.0),
    ("Toor Dal (loose)",          "TOORDAL",   "kg",     True,  95.0,  110.0, 20, 8,  "0713", 0.0),
    ("Moong Dal (loose)",         "MOONGDAL",  "kg",     True,  88.0,  100.0, 15, 6,  "0713", 0.0),
    ("Chana Dal (loose)",         "CHANADAL",  "kg",     True,  72.0,  85.0,  15, 6,  "0713", 0.0),
    ("Rice Basmati (loose)",      "BASMATI",   "kg",     True,  65.0,  78.0,  30, 10, "1006", 0.0),
    ("Rice Sona Masoori (loose)", "SONAMASRI", "kg",     True,  52.0,  62.0,  25, 10, "1006", 0.0),
    ("Sugar (loose)",             "SUGAR",     "kg",     True,  38.0,  45.0,  40, 15, "1701", 0.0),
    ("Wheat Flour (loose)",       "GEHUN",     "kg",     True,  28.0,  34.0,  30, 12, "1101", 0.0),
    ("Onion (loose)",             "ONION",     "kg",     True,  22.0,  30.0,  10, 5,  "0703", 0.0),
    ("Potato (loose)",            "POTATO",    "kg",     True,  18.0,  25.0,  10, 5,  "0701", 0.0),
    ("Tomato (loose)",            "TOMATO",    "kg",     True,  25.0,  35.0,  5,  3,  "0702", 0.0),
    ("Bournvita 500g",            "BOURNVITA", "piece",  False, 240.0, 275.0, 10, 4,  "1901", 18.0),
    ("Horlicks 500g",             "HORLICKS",  "piece",  False, 230.0, 265.0, 8,  4,  "1901", 18.0),
    ("MDH Garam Masala 100g",     "MDH100",    "packet", False, 45.0,  55.0,  15, 6,  "0910", 5.0),
    ("Everest Rajma Masala 50g",  "EVRAJMA",   "packet", False, 22.0,  28.0,  20, 8,  "0910", 5.0),
    ("Hajmola 25 tabs",           "HAJMOLA",   "piece",  False, 12.0,  15.0,  30, 10, "3004", 12.0),
    ("Frooti 200ml",              "FROOTI200", "piece",  False, 12.0,  15.0,  40, 15, "2202", 12.0),
    ("Coca Cola 750ml",           "COKE750",   "piece",  False, 38.0,  45.0,  24, 10, "2202", 12.0),
    ("Kurkure Masala Munch 73g",  "KURKURE73", "packet", False, 18.0,  22.0,  30, 12, "1905", 5.0),
]

DEFAULT_PREFERENCES = [
    ("shop_name", "Nebula Kirana Store"),
    ("shop_address", "123, Market Street, Your City - 560001"),
    ("gstin", "29AAAAA0000A1Z5"),
    ("default_payment", "cash"),
    ("shop_owner", "Store Owner"),
    ("phone", "9999999999"),
]


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)
    print("[OK] Tables created.")


def seed_products():
    """Insert seed products if they don't already exist."""
    with get_db() as db:
        existing = db.query(Product).count()
        if existing > 0:
            print(f"[INFO] {existing} products already in DB. Skipping product seed.")
            return

        for (name, sku, unit, is_loose, cost, mrp, qty,
             reorder, hsn, gst) in PRODUCTS:
            p = Product(
                name=name, sku=sku, unit=unit, is_loose=is_loose,
                cost_price=cost, mrp=mrp, quantity=qty,
                reorder_lvl=reorder, hsn_code=hsn, gst_slab=gst,
            )
            db.add(p)
        print(f"[OK] Seeded {len(PRODUCTS)} products.")


def seed_preferences():
    """Insert default preferences if they don't already exist."""
    with get_db() as db:
        from db.models import OwnerPreference
        for key, value in DEFAULT_PREFERENCES:
            exists = db.query(OwnerPreference).filter_by(key=key).first()
            if not exists:
                db.add(OwnerPreference(key=key, value=value))
        print("[OK] Default preferences seeded.")


def run():
    init_db()
    seed_products()
    seed_preferences()
    print("[READY] Database ready!")


if __name__ == "__main__":
    run()
