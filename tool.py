import asyncio
import logging
import os
from typing import Annotated, List, Optional, Dict, Any
from dotenv import load_dotenv
import asyncpg

from livekit import agents
from livekit.plugins import groq
from livekit.agents import AgentSession, Agent, RoomInputOptions, function_tool, RunContext
from livekit.plugins import (
    deepgram,
    silero,
)

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InventoryAssistant(Agent):
    # Dictionary mapping common item variations to their actual database names
    ITEM_MAPPINGS = {
        "cola": "Coke",
        "soda": "Coke",
        "coke": "Coke",
        "coca cola": "Coke",
        "coca-cola": "Coke",
        "chips": "Lays",
        "potato chips": "Lays",
        "lays": "Lays",
        "biscuit": "Bisckets",
        "cookies": "Bisckets",
        "biscuits": "Bisckets",
        "bisckets": "Bisckets"
    }

    # Variant mappings for different sizes/types
    VARIANT_MAPPINGS = {
        "regular": "Regular",
        "normal": "Regular",
        "small": "Regular",
        "half liter": "Half Liter",
        "half litre": "Half Liter",
        "500ml": "Half Liter",
        "medium": "Half Liter",
        "1.5 liter": "1.5 Liter",
        "1.5 litre": "1.5 Liter",
        "1500ml": "1.5 Liter",
        "large": "1.5 Liter",
        "big": "1.5 Liter"
    }

    # Dictionary mapping common category variations to their actual database names
    CATEGORY_MAPPINGS = {
        "drink": "Drinks",
        "drinks": "Drinks",
        "beverage": "Drinks",
        "beverages": "Drinks",
        "snack": "Snacks",
        "snacks": "Snacks",
        "chips": "Snacks",
        "biscuit": "Biscuits",
        "biscuits": "Biscuits",
        "cookie": "Biscuits",
        "cookies": "Biscuits"
    }

    def _format_message(self, message: str) -> str:
        """Remove any asterisks from messages and clean up formatting"""
        return message.replace('*', '').replace('**', '')

    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a helpful inbound call assistant for an inventory management system. 
            Speak naturally like a phone operator. Do not use any special formatting or symbols.
            Never use asterisks or stars in your responses.
            
            You can help users:
            - List items by category (drinks, snacks, biscuits)
            - Check stock availability for items and gives details about variants like quantity and price
            - Add items to cart with pricing calculations
            - Show current cart contents and total price
            - Complete purchase and confirm final order
            
            When users ask about categories or types of items, use the list_category_items function.
            When they want specific item details, use the get_stock_info function.
            When they want to buy something, use the add_to_cart function.
            
            Important formatting rules:
            - Never use asterisks (*) or stars in any responses
            - Never use markdown or text formatting
            - Just use plain text like a normal phone conversation
            - When listing variants, use simple text with commas or newlines
            - Speak naturally as if you're having a phone conversation"""
        )
        
        # Shopping cart to store items before purchase
        self.cart: List[Dict[str, Any]] = []
        
    def _map_item_name(self, item_name: str) -> str:
        """Map user input to actual database item names"""
        item_lower = item_name.lower().strip()
        mapped = self.ITEM_MAPPINGS.get(item_lower, item_name)
        logger.info(f"🔄 Item mapping: '{item_name}' -> '{item_lower}' -> '{mapped}'")
        return mapped

    def _map_variant_name(self, variant_name: str) -> str:
        """Map user input to actual database variant names"""
        variant_lower = variant_name.lower().strip()
        mapped = self.VARIANT_MAPPINGS.get(variant_lower, variant_name)
        logger.info(f"🔄 Variant mapping: '{variant_name}' -> '{variant_lower}' -> '{mapped}'")
        return mapped

    def _map_category_name(self, category_name: str) -> str:
        """Map user input to actual database category names"""
        category_lower = category_name.lower().strip()
        mapped = self.CATEGORY_MAPPINGS.get(category_lower, category_name)
        logger.info(f"🔄 Category mapping: '{category_name}' -> '{category_lower}' -> '{mapped}'")
        return mapped

    @function_tool
    async def get_item_variants(
        self,
        context: RunContext,
        item_name: Annotated[str, "Name of the item to get variants for"]
    ) -> str:
        """Get all available variants for a specific item with prices"""
        try:
            mapped_item = self._map_item_name(item_name)
            logger.info(f"🔍 Getting variants for: '{mapped_item}'")
            
            conn = await get_db_connection()
            try:
                query = """
                SELECT s.item_name, 
                    COALESCE(v.variant, 'Default') as variant, 
                    COALESCE(v.quantity, s.quantity) as quantity, 
                    COALESCE(v.unit, s.unit) as unit, 
                    COALESCE(v.price, 0) as price
                FROM stock_items s
                LEFT JOIN item_variants v ON s.id = v.stock_item_id
                WHERE LOWER(TRIM(s.item_name)) = LOWER(TRIM($1))
                ORDER BY variant
                """
                rows = await conn.fetch(query, mapped_item)
                
                if not rows:
                    return f"Sorry, I couldn't find '{item_name}' in our inventory."
                
                variants_info = []
                for row in rows:
                    variants_info.append(f"{row['variant']}: {row['quantity']} {row['unit']} at ${row['price']:.2f} each")
                
                variants_text = ", ".join(variants_info)
                return self._format_message(f"Available {rows[0]['item_name']} variants: {variants_text}")
                    
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"❌ Error getting variants: {e}")
            return f"Sorry, I encountered an error while getting variants for '{item_name}'. Please try again."

    @function_tool
    async def get_stock_info(
        self,
        context: RunContext,
        item_name: Annotated[str, "Name of the item to check stock for"],
        variant: Annotated[str, "Specific variant of the item (leave empty if not specified)"] = ""
    ) -> str:
        """Check stock information for a specific item and optionally a specific variant with prices"""
        try:
            mapped_item = self._map_item_name(item_name)
            logger.info(f"🔍 Getting stock info for: '{mapped_item}', variant: '{variant}'")
            
            conn = await get_db_connection()
            try:
                if variant and variant.strip():
                    mapped_variant = self._map_variant_name(variant)
                    query = """
                    SELECT s.item_name, 
                        COALESCE(v.variant, 'Default') as variant,
                        COALESCE(v.quantity, s.quantity) as quantity,
                        COALESCE(v.unit, s.unit) as unit,
                        COALESCE(v.price, 0) as price
                    FROM stock_items s
                    LEFT JOIN item_variants v ON s.id = v.stock_item_id
                    WHERE LOWER(TRIM(s.item_name)) = LOWER(TRIM($1))
                    AND (v.variant IS NULL OR LOWER(TRIM(v.variant)) = LOWER(TRIM($2)))
                    """
                    row = await conn.fetchrow(query, mapped_item, mapped_variant)
                    
                    if not row:
                        all_variants_query = """
                        SELECT COALESCE(v.variant, 'Default') as variant, COALESCE(v.price, s.price) as price
                        FROM stock_items s
                        LEFT JOIN item_variants v ON s.id = v.stock_item_id
                        WHERE LOWER(TRIM(s.item_name)) = LOWER(TRIM($1))
                        """
                        variants = await conn.fetch(all_variants_query, mapped_item)
                        if variants:
                            variant_list = [f"{v['variant']} (${v['price']:.2f})" for v in variants]
                            return self._format_message(f"Sorry, I couldn't find '{variant}' variant of {item_name}. Available variants are: {', '.join(variant_list)}")
                        return f"Sorry, I couldn't find '{item_name}' in our inventory."
                    
                    return f"We have {row['quantity']} {row['unit']} of {row['item_name']} ({row['variant']}) in stock at ${row['price']:.2f} per {row['unit']}."
                
                else:
                    query = """
                    SELECT s.item_name,
                        COALESCE(v.variant, 'Default') as variant,
                        COALESCE(v.quantity, s.quantity) as quantity,
                        COALESCE(v.unit, s.unit) as unit,
                        COALESCE(v.price, 0) as price
                    FROM stock_items s
                    LEFT JOIN item_variants v ON s.id = v.stock_item_id
                    WHERE LOWER(TRIM(s.item_name)) = LOWER(TRIM($1))
                    """
                    rows = await conn.fetch(query, mapped_item)
                    
                    if not rows:
                        return f"Sorry, I couldn't find '{item_name}' in our inventory."
                    
                    variants_info = []
                    for row in rows:
                        variants_info.append(f"{row['variant']}: {row['quantity']} {row['unit']} at ${row['price']:.2f} each")
                    
                    variants_text = ", ".join(variants_info)
                    return self._format_message(f"We have {rows[0]['item_name']} available in these options: {variants_text}")
                    
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"❌ Error checking stock: {e}")
            return f"Sorry, I encountered an error while checking stock for '{item_name}'. Please try again."

    @function_tool
    async def add_to_cart(
        self,
        context: RunContext,
        item_name: Annotated[str, "Name of the item to add to cart"],
        quantity: Annotated[int, "Quantity to add to cart"],
        variant: Annotated[str, "Specific variant of the item (leave empty if not specified)"] = ""
    ) -> str:
        """Add items to cart (does not reduce stock yet)"""
        try:
            mapped_item = self._map_item_name(item_name)
            mapped_variant = self._map_variant_name(variant) if variant and variant.strip() else "Default"
            
            conn = await get_db_connection()
            try:
                find_query = """
                SELECT s.id as stock_item_id, 
                    s.item_name,
                    COALESCE(v.variant, 'Default') as variant,
                    COALESCE(v.quantity, s.quantity) as quantity,
                    COALESCE(v.unit, s.unit) as unit,
                    COALESCE(v.price, 0) as price,
                    v.id as variant_id
                FROM stock_items s
                LEFT JOIN item_variants v ON s.id = v.stock_item_id
                WHERE LOWER(TRIM(s.item_name)) = LOWER(TRIM($1))
                AND (v.variant IS NULL OR LOWER(TRIM(v.variant)) = LOWER(TRIM($2)))
                """
                item = await conn.fetchrow(find_query, mapped_item, mapped_variant)
                
                if not item:
                    variants_query = """
                    SELECT COALESCE(v.variant, 'Default') as variant, COALESCE(v.price, s.price) as price
                    FROM stock_items s
                    LEFT JOIN item_variants v ON s.id = v.stock_item_id
                    WHERE LOWER(TRIM(s.item_name)) = LOWER(TRIM($1))
                    """
                    variants = await conn.fetch(variants_query, mapped_item)
                    if variants:
                        variant_list = [f"{v['variant']} (${v['price']:.2f})" for v in variants]
                        return self._format_message(f"Sorry, I couldn't find '{variant}' variant of {item_name}. Available options are: {', '.join(variant_list)}")
                    return f"Sorry, I couldn't find '{item_name}' in our inventory."
                
                if item['quantity'] < quantity:
                    return f"Sorry, we only have {item['quantity']} {item['unit']} of {item['item_name']} ({item['variant']}) available."
                
                item_total = float(item['price']) * quantity
                
                cart_item = {
                    'item_name': item['item_name'],
                    'variant': item['variant'],
                    'quantity': quantity,
                    'unit': item['unit'],
                    'price_per_unit': float(item['price']),
                    'total_price': item_total,
                    'variant_id': item['variant_id'],
                    'stock_item_id': item['stock_item_id']
                }
                
                self.cart.append(cart_item)
                cart_total = sum(item['total_price'] for item in self.cart)
                
                return f"Added {quantity} {item['unit']} of {item['item_name']} ({item['variant']}) to cart at ${item['price']:.2f} each = ${item_total:.2f}. Cart total: ${cart_total:.2f}"
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"❌ Error adding to cart: {e}")
            return f"Sorry, I encountered an error while adding {quantity} {item_name} to cart. Please try again."

    @function_tool
    async def show_cart(
        self,
        context: RunContext
    ) -> str:
        """Show current cart contents and total price"""
        try:
            if not self.cart:
                return "Your cart is empty."
            
            cart_details = []
            total_price = 0
            
            for item in self.cart:
                item_line = f"{item['quantity']} {item['unit']} of {item['item_name']} ({item['variant']}) - ${item['price_per_unit']:.2f} each = ${item['total_price']:.2f}"
                cart_details.append(item_line)
                total_price += item['total_price']
            
            cart_summary = "\n".join(cart_details)
            return f"Your cart:\n{cart_summary}\n\nTotal: ${total_price:.2f}"
            
        except Exception as e:
            logger.error(f"❌ Error showing cart: {e}")
            return "Sorry, I encountered an error while showing your cart."

    @function_tool
    async def clear_cart(
        self,
        context: RunContext
    ) -> str:
        """Clear all items from cart"""
        try:
            self.cart.clear()
            return "Cart cleared successfully."
        except Exception as e:
            logger.error(f"❌ Error clearing cart: {e}")
            return "Sorry, I encountered an error while clearing your cart."

    @function_tool
    async def complete_purchase(
        self,
        context: RunContext
    ) -> str:
        """Complete the purchase of all items in cart (reduces stock)"""
        try:
            if not self.cart:
                return "Your cart is empty. Please add items before completing purchase."
            
            conn = await get_db_connection()
            try:
                # Start transaction
                async with conn.transaction():
                    purchase_details = []
                    total_amount = 0
                    
                    for cart_item in self.cart:
                        # Verify stock is still available
                        if cart_item.get('variant_id'):
                            # Item with variant
                            check_query = """
                            SELECT quantity FROM item_variants WHERE id = $1
                            """
                            current_stock = await conn.fetchval(check_query, cart_item['variant_id'])
                            
                            if current_stock is None or current_stock < cart_item['quantity']:
                                return f"Sorry, {cart_item['item_name']} ({cart_item['variant']}) is no longer available in the requested quantity. Please check stock and try again."
                            
                            # Update variant stock
                            new_quantity = current_stock - cart_item['quantity']
                            update_query = """
                            UPDATE item_variants 
                            SET quantity = $1 
                            WHERE id = $2
                            """
                            await conn.execute(update_query, new_quantity, cart_item['variant_id'])
                            
                        else:
                            # Item without variant (fallback)
                            check_query = """
                            SELECT quantity FROM stock_items WHERE id = $1
                            """
                            current_stock = await conn.fetchval(check_query, cart_item['stock_item_id'])
                            
                            if current_stock is None or current_stock < cart_item['quantity']:
                                return f"Sorry, {cart_item['item_name']} is no longer available in the requested quantity. Please check stock and try again."
                            
                            new_quantity = current_stock - cart_item['quantity']
                            update_query = """
                            UPDATE stock_items 
                            SET quantity = $1 
                            WHERE id = $2
                            """
                            await conn.execute(update_query, new_quantity, cart_item['stock_item_id'])
                        
                        # Add to purchase summary
                        purchase_details.append(
                            f"{cart_item['quantity']} {cart_item['unit']} of {cart_item['item_name']} ({cart_item['variant']}) - ${cart_item['total_price']:.2f}"
                        )
                        total_amount += cart_item['total_price']
                    
                    # Clear cart after successful purchase
                    self.cart.clear()
                    
                    purchase_summary = "\n".join(purchase_details)
                    return f"✅ Purchase completed successfully!\n\nOrder details:\n{purchase_summary}\n\nTotal amount: ${total_amount:.2f}\n\nThank you for your purchase!"
                    
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"❌ Error completing purchase: {e}")
            return "Sorry, I encountered an error while processing your purchase. Please try again."

    @function_tool
    async def list_category_items(
        self,
        context: RunContext,
        category: Annotated[str, "Category name to list items for"]
    ) -> str:
        """List all available items in a specific category"""
        try:
            mapped_category = self._map_category_name(category)
            
            conn = await get_db_connection()
            try:
                query = """
                SELECT DISTINCT s.item_name,
                    CASE 
                        WHEN COUNT(v.id) > 0 THEN true 
                        ELSE false 
                    END as has_variants
                FROM stock_items s
                JOIN categories c ON s.category_id = c.id
                LEFT JOIN item_variants v ON s.id = v.stock_item_id
                WHERE LOWER(c.name) = LOWER($1)
                GROUP BY s.item_name
                """
                rows = await conn.fetch(query, mapped_category)
                
                if not rows:
                    return f"No items found in the {category} category."
                
                items = []
                for row in rows:
                    item_name = row['item_name']
                    if row['has_variants']:
                        items.append(f"{item_name} (multiple variants available)")
                    else:
                        items.append(item_name)
                
                items_text = "\n- ".join(items)
                return f"Available items in {mapped_category}:\n- {items_text}"
                
            finally:
                await conn.close()
                
        except Exception as e:
            logger.error(f"❌ Error listing category items: {e}")
            return f"Sorry, I encountered an error while listing items in {category}."

    # Keep the old purchase_item function for backward compatibility, but redirect to cart system
    @function_tool
    async def purchase_item(
        self,
        context: RunContext,
        item_name: Annotated[str, "Name of the item to purchase"],
        quantity: Annotated[int, "Quantity to purchase"],
        variant: Annotated[str, "Specific variant of the item (leave empty if not specified)"] = ""
    ) -> str:
        """Legacy purchase function - redirects to cart system"""
        # Add to cart first
        add_result = await self.add_to_cart(context, item_name, quantity, variant)
        
        if "Added" in add_result:
            # If successfully added, show cart and ask for confirmation
            cart_result = await self.show_cart(context)
            return f"{add_result}\n\n{cart_result}\n\nWould you like to complete this purchase or add more items?"
        else:
            return add_result


# Database connection helper
async def get_db_connection():
    """Get database connection"""
    try:
        database_url = os.getenv("DATABASE_URL")
        if database_url:
            conn = await asyncpg.connect(database_url)
        else:
            conn = await asyncpg.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", 5432)),
                user=os.getenv("DB_USER", "postgres"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME", "store_inventory")
            )
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise



async def entrypoint(ctx: agents.JobContext):
    # Initialize the agent session
    session = AgentSession(
        stt=deepgram.STT(model="nova-2", language="multi"),
        llm=groq.LLM(model="moonshotai/kimi-k2-instruct"),
        tts=deepgram.TTS(model="aura-luna-en"),
        vad=silero.VAD.load(),
    )

    await session.start(
        room=ctx.room,
        agent=InventoryAssistant(),
        room_input_options=RoomInputOptions(),
    )

    await session.generate_reply(
        instructions="Greet the user. Ask how you can help them today with inventory management. Mention that you can help them check stock, add items to cart, and complete purchases."
    )

if __name__ == "__main__":
    agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))