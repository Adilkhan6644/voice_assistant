from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
import asyncpg
import os
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Inventory Management API",
    description="FastAPI endpoints for stock inventory CRUD operations",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure as needed for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class StockItemBase(BaseModel):
    item_name: str = Field(..., description="Name of the item")
    quantity: int = Field(..., ge=0, description="Quantity of the item (must be >= 0)")
    unit: str = Field(..., description="Unit of measurement (e.g., carton, kg, pieces)")

class StockItemCreate(StockItemBase):
    pass

class StockItemUpdate(BaseModel):
    item_name: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=0)
    unit: Optional[str] = None

class StockItem(StockItemBase):
    id: int
    
    class Config:
        from_attributes = True

class PurchaseRequest(BaseModel):
    item_id: int = Field(..., description="ID of the item to purchase")
    quantity: int = Field(..., gt=0, description="Quantity to purchase (must be > 0)")

class PurchaseResponse(BaseModel):
    message: str
    item_name: str
    purchased_quantity: int
    remaining_quantity: int

# Database connection
async def get_db_connection():
    """Get database connection"""
    try:
        # Try DATABASE_URL first, then fall back to individual parameters
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            conn = await asyncpg.connect(database_url)
        else:
            conn = await asyncpg.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=os.getenv("DB_PORT", 5432),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME", "store_inventory")
            )
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")

@app.on_event("startup")
async def startup_event():
    """Test database connection on startup"""
    try:
        conn = await get_db_connection()
        await conn.close()
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed on startup: {e}")

# API Endpoints

@app.get("/", summary="Root endpoint")
async def root():
    """Welcome message"""
    return {"message": "Inventory Management API", "version": "1.0.0"}

@app.get("/health", summary="Health check")
async def health_check():
    """Check API and database health"""
    try:
        conn = await get_db_connection()
        await conn.fetchval("SELECT 1")
        await conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {str(e)}")

@app.get("/stocks", response_model=List[StockItem], summary="Get all stock items")
async def get_all_stocks():
    """Retrieve all stock items from the database"""
    conn = await get_db_connection()
    try:
        query = "SELECT id, item_name, quantity, unit FROM stock_items ORDER BY id"
        rows = await conn.fetch(query)
        return [StockItem(**dict(row)) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching stocks: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stock items")
    finally:
        await conn.close()

@app.get("/stocks/{item_id}", response_model=StockItem, summary="Get stock item by ID")
async def get_stock_by_id(item_id: int):
    """Retrieve a specific stock item by its ID"""
    conn = await get_db_connection()
    try:
        query = "SELECT id, item_name, quantity, unit FROM stock_items WHERE id = $1"
        row = await conn.fetchrow(query, item_id)
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Stock item with ID {item_id} not found")
        
        return StockItem(**dict(row))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stock {item_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stock item")
    finally:
        await conn.close()

@app.get("/stocks/search/{item_name}", response_model=List[StockItem], summary="Search stocks by name")
async def search_stocks_by_name(item_name: str):
    """Search stock items by name (case-insensitive partial match)"""
    conn = await get_db_connection()
    try:
        query = """
        SELECT id, item_name, quantity, unit 
        FROM stock_items 
        WHERE LOWER(item_name) LIKE LOWER($1) 
        ORDER BY item_name
        """
        rows = await conn.fetch(query, f"%{item_name}%")
        return [StockItem(**dict(row)) for row in rows]
    except Exception as e:
        logger.error(f"Error searching stocks: {e}")
        raise HTTPException(status_code=500, detail="Failed to search stock items")
    finally:
        await conn.close()

@app.post("/stocks", response_model=StockItem, summary="Add new stock item", status_code=201)
async def add_stock(stock_item: StockItemCreate):
    """Add a new stock item to the inventory"""
    conn = await get_db_connection()
    try:
        # Check if item already exists
        check_query = "SELECT id FROM stock_items WHERE LOWER(item_name) = LOWER($1)"
        existing_item = await conn.fetchval(check_query, stock_item.item_name)
        
        if existing_item:
            raise HTTPException(
                status_code=400, 
                detail=f"Item '{stock_item.item_name}' already exists. Use PUT to update quantity."
            )
        
        # Insert new item
        query = """
        INSERT INTO stock_items (item_name, quantity, unit) 
        VALUES ($1, $2, $3) 
        RETURNING id, item_name, quantity, unit
        """
        row = await conn.fetchrow(query, stock_item.item_name, stock_item.quantity, stock_item.unit)
        
        return StockItem(**dict(row))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding stock: {e}")
        raise HTTPException(status_code=500, detail="Failed to add stock item")
    finally:
        await conn.close()

@app.put("/stocks/{item_id}", response_model=StockItem, summary="Update stock item")
async def update_stock(item_id: int, stock_update: StockItemUpdate):
    """Update an existing stock item"""
    conn = await get_db_connection()
    try:
        # Check if item exists
        check_query = "SELECT id FROM stock_items WHERE id = $1"
        existing_item = await conn.fetchval(check_query, item_id)
        
        if not existing_item:
            raise HTTPException(status_code=404, detail=f"Stock item with ID {item_id} not found")
        
        # Build dynamic update query
        update_fields = []
        values = []
        param_count = 1
        
        if stock_update.item_name is not None:
            update_fields.append(f"item_name = ${param_count}")
            values.append(stock_update.item_name)
            param_count += 1
            
        if stock_update.quantity is not None:
            update_fields.append(f"quantity = ${param_count}")
            values.append(stock_update.quantity)
            param_count += 1
            
        if stock_update.unit is not None:
            update_fields.append(f"unit = ${param_count}")
            values.append(stock_update.unit)
            param_count += 1
        
        if not update_fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        values.append(item_id)  # Add item_id for WHERE clause
        
        query = f"""
        UPDATE stock_items 
        SET {', '.join(update_fields)} 
        WHERE id = ${param_count} 
        RETURNING id, item_name, quantity, unit
        """
        
        row = await conn.fetchrow(query, *values)
        return StockItem(**dict(row))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating stock {item_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update stock item")
    finally:
        await conn.close()

class AddQuantityRequest(BaseModel):
    quantity_to_add: int = Field(..., gt=0, description="Quantity to add to stock")

@app.post("/stocks/{item_id}/add-quantity", response_model=StockItem, summary="Add quantity to existing stock")
async def add_quantity_to_stock(item_id: int, request: AddQuantityRequest):
    """Add quantity to an existing stock item (for restocking)"""
    conn = await get_db_connection()
    try:
        query = """
        UPDATE stock_items 
        SET quantity = quantity + $1 
        WHERE id = $2 
        RETURNING id, item_name, quantity, unit
        """
        
        row = await conn.fetchrow(query, request.quantity_to_add, item_id)
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Stock item with ID {item_id} not found")
        
        return StockItem(**dict(row))
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding quantity to stock {item_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to add quantity to stock item")
    finally:
        await conn.close()

@app.post("/purchase", response_model=PurchaseResponse, summary="Purchase items from stock")
async def purchase_item(purchase: PurchaseRequest):
    """Purchase items from stock (reduces quantity)"""
    conn = await get_db_connection()
    try:
        # Start a transaction
        async with conn.transaction():
            # Get current stock
            query = "SELECT id, item_name, quantity, unit FROM stock_items WHERE id = $1"
            row = await conn.fetchrow(query, purchase.item_id)
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Stock item with ID {purchase.item_id} not found")
            
            current_stock = dict(row)
            
            # Check if enough stock is available
            if current_stock['quantity'] < purchase.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock. Available: {current_stock['quantity']}, Requested: {purchase.quantity}"
                )
            
            # Update stock quantity
            new_quantity = current_stock['quantity'] - purchase.quantity
            update_query = """
            UPDATE stock_items 
            SET quantity = $1 
            WHERE id = $2 
            RETURNING quantity
            """
            
            updated_quantity = await conn.fetchval(update_query, new_quantity, purchase.item_id)
            
            return PurchaseResponse(
                message=f"Successfully purchased {purchase.quantity} {current_stock['unit']} of {current_stock['item_name']}",
                item_name=current_stock['item_name'],
                purchased_quantity=purchase.quantity,
                remaining_quantity=updated_quantity
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing purchase: {e}")
        raise HTTPException(status_code=500, detail="Failed to process purchase")
    finally:
        await conn.close()

@app.delete("/stocks/{item_id}", summary="Delete stock item")
async def delete_stock(item_id: int):
    """Delete a stock item from inventory"""
    conn = await get_db_connection()
    try:
        query = "DELETE FROM stock_items WHERE id = $1 RETURNING id, item_name"
        row = await conn.fetchrow(query, item_id)
        
        if not row:
            raise HTTPException(status_code=404, detail=f"Stock item with ID {item_id} not found")
        
        return {"message": f"Stock item '{row['item_name']}' (ID: {row['id']}) deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting stock {item_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete stock item")
    finally:
        await conn.close()

@app.get("/stocks/low-stock/{threshold}", response_model=List[StockItem], summary="Get low stock items")
async def get_low_stock_items(threshold: int):
    """Get items with stock quantity below the specified threshold"""
    conn = await get_db_connection()
    try:
        query = """
        SELECT id, item_name, quantity, unit 
        FROM stock_items 
        WHERE quantity < $1 
        ORDER BY quantity ASC
        """
        rows = await conn.fetch(query, threshold)
        return [StockItem(**dict(row)) for row in rows]
    except Exception as e:
        logger.error(f"Error fetching low stock items: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch low stock items")
    finally:
        await conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)