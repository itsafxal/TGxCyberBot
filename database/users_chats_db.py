import motor.motor_asyncio
from info import DATABASE_NAME, DATABASE_URI
from collections import OrderedDict
import time

class LRUCache:
    def __init__(self, max_size=10000, ttl=86400):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl

    def get(self, key):
        if key in self.cache:
            val, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                self.cache.move_to_end(key)
                return val
            else:
                del self.cache[key]
        return None

    def set(self, key, val):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (val, time.time())
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

    def delete(self, key):
        self.cache.pop(key, None)

_USER_CACHE = LRUCache(max_size=10000, ttl=86400)
_CHAT_CACHE = LRUCache(max_size=5000, ttl=86400)

class Database:
    
    def __init__(self, uri, database_name):
        self._client = motor.motor_asyncio.AsyncIOMotorClient(uri)
        self.db = self._client[database_name]
        self.col = self.db.users
        self.grp = self.db.groups
        self.req_one = self.db.reqone
        self.req_two = self.db.reqtwo
        self.req_three = self.db.reqthree
        self.chat_col = self.db.chatcol
        self.chat_col2 = self.db.chatcol2
        self.adm = self.db.admins
        self.admn = self.db.admin
        self.auto_del_col = self.db.auto_delete_queue
        self.trash_col = self.db.trash_messages
        self.settings_col = self.db.settings

    def new_user(self, id, name):
        return dict(
            id = int(id),
            name = name or "User",
            ban_status=dict(
                is_banned=False,
                ban_reason="",
            ),
        )


    def new_group(self, id, title):
        return dict(
            id = int(id),
            title = title or "Group",
            chat_status=dict(
                is_disabled=False,
                reason="",
            ),
        )
    
    async def add_user(self, id, name=None):
        if not id:
            return
        id_int = int(id)
        _USER_CACHE.set(id_int, True)
        if not await self.is_user_exist(id_int):
            user = self.new_user(id_int, name or "User")
            try:
                await self.col.insert_one(user)
            except Exception as e:
                pass
    
    async def is_user_exist(self, id):
        if not id:
            return False
        id_int = int(id)
        cached = _USER_CACHE.get(id_int)
        if cached is not None:
            return cached
        try:
            user = await self.col.find_one({'id': id_int})
            exists = bool(user)
            if exists:
                _USER_CACHE.set(id_int, True)
            return exists
        except Exception:
            return False
    
    async def total_users_count(self):
        count = await self.col.count_documents({})
        return count
    
    async def remove_ban(self, id):
        ban_status = dict(
            is_banned=False,
            ban_reason=''
        )
        await self.col.update_one({'id': id}, {'$set': {'ban_status': ban_status}})
    
    async def ban_user(self, user_id, ban_reason="No Reason"):
        ban_status = dict(
            is_banned=True,
            ban_reason=ban_reason
        )
        await self.col.update_one({'id': user_id}, {'$set': {'ban_status': ban_status}})

    async def get_ban_status(self, id):
        default = dict(
            is_banned=False,
            ban_reason=''
        )
        user = await self.col.find_one({'id':int(id)})
        if not user:
            return default
        return user.get('ban_status', default)

    async def get_all_users(self):
        return self.col.find({})
    

    async def delete_user(self, user_id):
        await self.col.delete_many({'id': int(user_id)})


    async def get_banned(self):
        users = self.col.find({'ban_status.is_banned': True})
        chats = self.grp.find({'chat_status.is_disabled': True})
        b_chats = [chat['id'] async for chat in chats]
        b_users = [user['id'] async for user in users]
        return b_users, b_chats
    


    async def add_chat(self, chat, title):
        chat_id = int(chat)
        _CHAT_CACHE.set(chat_id, {"is_disabled": False, "reason": ""})
        chat_doc = self.new_group(chat_id, title)
        try:
            await self.grp.insert_one(chat_doc)
        except Exception:
            pass
    

    async def get_chat(self, chat):
        if not chat:
            return False
        chat_id = int(chat)
        cached = _CHAT_CACHE.get(chat_id)
        if cached is not None:
            return cached
        try:
            chat_doc = await self.grp.find_one({'id': chat_id})
            status = False if not chat_doc else chat_doc.get('chat_status', {"is_disabled": False, "reason": ""})
            if status is not False:
                _CHAT_CACHE.set(chat_id, status)
            return status
        except Exception:
            return False
    

    async def re_enable_chat(self, id):
        chat_id = int(id)
        chat_status=dict(
            is_disabled=False,
            reason="",
            )
        _CHAT_CACHE.set(chat_id, chat_status)
        await self.grp.update_one({'id': chat_id}, {'$set': {'chat_status': chat_status}})
        
    async def disable_chat(self, chat, reason="No Reason"):
        chat_id = int(chat)
        chat_status=dict(
            is_disabled=True,
            reason=reason,
            )
        _CHAT_CACHE.set(chat_id, chat_status)
        await self.grp.update_one({'id': chat_id}, {'$set': {'chat_status': chat_status}})
    

    async def total_chat_count(self):
        count = await self.grp.count_documents({})
        return count
    

    async def get_all_chats(self):
        return self.grp.find({})


    async def get_db_size(self):
        return (await self.db.command("dbstats"))['dataSize']

    async def add_req_one(self, user_id):
        try:
            await self.req_one.insert_one({"user_id": int(user_id)})
            return
        except Exception as e:
            print(e)
            pass
        
    async def add_req_two(self, user_id):
        try:
            await self.req_two.insert_one({"id": int(user_id)})
            return
        except Exception as e:
            print(e)
            pass

    async def add_req_three(self, user_id):
        try:
            await self.req_three.insert_one({"id": int(user_id)})
            return
        except Exception as e:
            print(e)
            pass
            
    async def get_req_one(self, user_id):
        return await self.req_one.find_one({"user_id": int(user_id)})

    async def get_req_two(self, user_id):
        return await self.req_two.find_one({"id": int(user_id)})

    async def get_req_three(self, user_id):
        return await self.req_three.find_one({"id": int(user_id)})

    async def delete_all_one(self):
        await self.req_one.delete_many({})

    async def delete_all_two(self):
        await self.req_two.delete_many({})

    async def delete_all_three(self):
        await self.req_three.delete_many({})

    async def get_all_one_count(self): 
        count = 0
        async for req in self.req_one.find({}):
            count += 1
        return count

    async def get_all_two_count(self): 
        count = 0
        async for req in self.req_two.find({}):
            count += 1
        return count

    async def get_all_three_count(self): 
        count = 0
        async for req in self.req_three.find({}):
            count += 1
        return count

    async def get_loadout(self, id: int):
        data = await self.adm.find_one({'id': id})
        if not data:
            data = {
                'id': id,
                'channel1': None,
                'channel2': None,
                'channel3': None,
                'channel1_2': None,
                'channel2_2': None,
                'channel3_2': None,
                'channel1_threshold': None,
                'channel2_threshold': None,
                'channel3_threshold': None
            }
            print("New Loadout Created....")
            await self.adm.insert_one(data)
        else:
            updated = False
            for key in ['channel1', 'channel2', 'channel3', 'channel1_2', 'channel2_2', 'channel3_2',
                        'channel1_threshold', 'channel2_threshold', 'channel3_threshold']:
                if key not in data:
                    data[key] = None
                    updated = True
            if updated:
                await self.adm.update_one({'id': id}, {'$set': data})
        return data

    async def get_autofilter(self):
        try:
            data = await self.adm.find_one({'id': 'auto'})
            if not data:
                data = await self.admn.find_one({'id': 'auto'})
            if not data:
                data = {
                    'id': 'auto',
                    'autofilter': True
                }
                await self.adm.insert_one(data)
            return data
        except Exception:
            return {'id': 'auto', 'autofilter': True}

    async def update_autofilter(self, value: bool):
        try:
            await self.adm.update_one({'id': 'auto'}, {'$set': {'autofilter': value}}, upsert=True)
            await self.admn.update_one({'id': 'auto'}, {'$set': {'autofilter': value}}, upsert=True)
        except Exception as e:
            print(f"Error updating autofilter: {e}")
        await self.adm.update_one({'id': 'auto'}, {'$set': {'autofilter': value}})

    async def update_loadout(self, key, value, id: int):
        await self.adm.update_one({'id': id}, {'$set': {key: value}})

    async def update_cout(self, key: str, value: int):
        await self.adm.update_many({}, {'$set': {f"{key}_threshold": value}})

    async def get_del_settings(self):
        data = await self.settings_col.find_one({'id': 'del_settings'})
        if not data:
            data = {
                'id': 'del_settings',
                'filter_del_time': 300,
                'file_del_time': 900
            }
            await self.settings_col.insert_one(data)
        return data

    async def update_filter_del_time(self, seconds: int):
        await self.settings_col.update_one(
            {'id': 'del_settings'},
            {'$set': {'filter_del_time': int(seconds)}},
            upsert=True
        )

    async def update_file_del_time(self, seconds: int):
        await self.settings_col.update_one(
            {'id': 'del_settings'},
            {'$set': {'file_del_time': int(seconds)}},
            upsert=True
        )

    async def add_to_auto_delete(self, chat_id: int, message_id: int, delete_at: float, msg_type: str = "general", file_id: str = None):
        doc = {
            'chat_id': int(chat_id),
            'message_id': int(message_id),
            'delete_at': float(delete_at),
            'msg_type': msg_type
        }
        if file_id:
            doc['file_id'] = str(file_id)
        await self.auto_del_col.update_one(
            {'chat_id': int(chat_id), 'message_id': int(message_id)},
            {'$set': doc},
            upsert=True
        )

    async def get_due_auto_delete_messages(self, current_time: float):
        cursor = self.auto_del_col.find({'delete_at': {'$lte': float(current_time)}})
        return await cursor.to_list(length=None)

    async def remove_from_auto_delete(self, chat_id: int, message_id: int):
        await self.auto_del_col.delete_one({'chat_id': int(chat_id), 'message_id': int(message_id)})

    async def add_trash_message(self, chat_id: int, message_id: int):
        doc = {
            'chat_id': int(chat_id),
            'message_id': int(message_id)
        }
        await self.trash_col.update_one(
            {'chat_id': int(chat_id), 'message_id': int(message_id)},
            {'$set': doc},
            upsert=True
        )

    async def get_all_trash_messages(self):
        cursor = self.trash_col.find({})
        return await cursor.to_list(length=None)

    async def remove_trash_messages(self, chat_id: int, message_ids: list):
        if not message_ids:
            return
        await self.trash_col.delete_many({
            'chat_id': int(chat_id),
            'message_id': {'$in': [int(m) for m in message_ids]}
        })

    async def delete_all_trash_from_db(self):
        await self.trash_col.delete_many({})
        await self.auto_del_col.delete_many({})

db = Database(DATABASE_URI, DATABASE_NAME)
