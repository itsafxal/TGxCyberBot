import pymongo
import logging
from info import DATABASE_URI, DATABASE_NAME
from pyrogram import enums

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

# MongoDB connection
myclient = pymongo.MongoClient(DATABASE_URI)
mydb = myclient[DATABASE_NAME]


async def add_gfilter(gfilters, text, reply_text, btn, file, alert):
    """
    Add a global filter to the database
    
    Args:
        gfilters (str): Collection name
        text (str): Filter keyword
        reply_text (str): Response text
        btn (str): JSON string of buttons
        file (str): File ID
        alert (str): Alert text
    """
    mycol = mydb[str(gfilters)]
    # Create text index for faster searching if needed
    # mycol.create_index([('text', 'text')])

    data = {
        'text': str(text),
        'reply': str(reply_text),
        'btn': str(btn),
        'file': str(file),
        'alert': str(alert)
    }

    try:
        mycol.update_one({'text': str(text)}, {"$set": data}, upsert=True)
    except Exception as e:
        logger.exception('Error adding global filter', exc_info=True)


async def find_gfilter(gfilters, name):
    """
    Find a global filter by name
    
    Args:
        gfilters (str): Collection name
        name (str): Filter keyword to find
        
    Returns:
        tuple: (reply_text, buttons, alert, file_id)
    """
    mycol = mydb[str(gfilters)]
    
    query = mycol.find({"text": name})
    # Alternative using text search:
    # query = mycol.find({"$text": {"$search": name}})
    
    try:
        for file in query:
            reply_text = file['reply']
            btn = file['btn']
            fileid = file['file']
            try:
                alert = file['alert']
            except:
                alert = None
        return reply_text, btn, alert, fileid
    except:
        return None, None, None, None


async def get_gfilters(gfilters):
    """
    Get all global filter keywords
    
    Args:
        gfilters (str): Collection name
        
    Returns:
        list: List of filter keywords
    """
    mycol = mydb[str(gfilters)]

    texts = []
    query = mycol.find()
    try:
        for file in query:
            text = file['text']
            texts.append(text)
    except:
        pass
    return texts


async def delete_gfilter(message, text, gfilters):
    """
    Delete a global filter
    
    Args:
        message: Message object for reply
        text (str): Filter keyword to delete
        gfilters (str): Collection name
    """
    mycol = mydb[str(gfilters)]
    
    myquery = {'text': text}
    query = mycol.count_documents(myquery)
    if query == 1:
        mycol.delete_one(myquery)
        await message.reply_text(
            f"'`{text}`' deleted. I'll not respond to that gfilter anymore.",
            quote=True,
            parse_mode=enums.ParseMode.MARKDOWN
        )
    else:
        await message.reply_text("Couldn't find that gfilter!", quote=True)


async def del_allg(message, gfilters):
    """
    Delete all global filters
    
    Args:
        message: Message object for reply
        gfilters (str): Collection name
    """
    if str(gfilters) not in mydb.list_collection_names():
        await message.edit_text("Nothing to remove!")
        return

    mycol = mydb[str(gfilters)]
    try:
        mycol.drop()
        await message.edit_text(f"All gfilters have been removed!")
    except:
        await message.edit_text("Couldn't remove all gfilters!")
        return


async def count_gfilters(gfilters):
    """
    Count global filters
    
    Args:
        gfilters (str): Collection name
        
    Returns:
        int or False: Number of filters or False if none
    """
    mycol = mydb[str(gfilters)]

    count = mycol.count_documents({})
    return False if count == 0 else count


async def gfilter_stats():
    """
    Get statistics for all collections
    
    Returns:
        tuple: (total_collections, total_count)
    """
    collections = mydb.list_collection_names()

    if "CONNECTION" in collections:
        collections.remove("CONNECTION")

    totalcount = 0
    for collection in collections:
        mycol = mydb[collection]
        count = mycol.count_documents({})
        totalcount += count

    totalcollections = len(collections)

    return totalcollections, totalcount
