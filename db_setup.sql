-- Create categories table if it doesn't exist
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT
);

-- Add category_id to stock_items if it doesn't exist
DO $$ 
BEGIN 
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name='stock_items' 
        AND column_name='category_id'
    ) THEN
        ALTER TABLE stock_items 
        ADD COLUMN category_id INTEGER REFERENCES categories(id);
    END IF;
END $$;

-- Insert base categories
INSERT INTO categories (name, description) 
VALUES 
    ('Drinks', 'Beverages and liquid refreshments'),
    ('Snacks', 'Chips and savory snacks'),
    ('Biscuits', 'Cookies and biscuits')
ON CONFLICT (name) DO NOTHING;

-- Update existing items with their categories
UPDATE stock_items 
SET category_id = (SELECT id FROM categories WHERE name = 'Drinks')
WHERE LOWER(item_name) = 'coke';

UPDATE stock_items 
SET category_id = (SELECT id FROM categories WHERE name = 'Snacks')
WHERE LOWER(item_name) = 'lays';

UPDATE stock_items 
SET category_id = (SELECT id FROM categories WHERE name = 'Biscuits')
WHERE LOWER(item_name) = 'bisckets';
