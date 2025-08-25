# https://github.com/odysseusmax/animated-lamp/blob/master/bot/database/database.py
import motor.motor_asyncio
from info import DATABASE_NAME, DATABASE_URI

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

    def new_user(self, id, name):
        return dict(
            id = id,
            name = name,
            ban_status=dict(
                is_banned=False,
                ban_reason="",
            ),
        )


    def new_group(self, id, title):
        return dict(
            id = id,
            title = title,
            chat_status=dict(
                is_disabled=False,
                reason="",
            ),
        )
    
    async def add_user(self, id, name):
        user = self.new_user(id, name)
        await self.col.insert_one(user)
    
    async def is_user_exist(self, id):
        user = await self.col.find_one({'id':int(id)})
        return bool(user)
    
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
        chat = self.new_group(chat, title)
        await self.grp.insert_one(chat)
    

    async def get_chat(self, chat):
        chat = await self.grp.find_one({'id':int(chat)})
        return False if not chat else chat.get('chat_status')
    

    async def re_enable_chat(self, id):
        chat_status=dict(
            is_disabled=False,
            reason="",
            )
        await self.grp.update_one({'id': int(id)}, {'$set': {'chat_status': chat_status}})
        
    async def disable_chat(self, chat, reason="No Reason"):
        chat_status=dict(
            is_disabled=True,
            reason=reason,
            )
        await self.grp.update_one({'id': int(chat)}, {'$set': {'chat_status': chat_status}})
    

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
        data = await self.admn.find_one({'id': 'auto'})
        if not data:
            data = {
                'id': 'auto',
                'autofilter': True
            }
            await self.admn.insert_one(data)
        return data

    async def update_autofilter(self, value):
        await self.adm.update_one({'id': 'auto'}, {'$set': {'autofilter': value}})

    async def update_loadout(self, key, value, id: int):
        await self.adm.update_one({'id': id}, {'$set': {key: value}})

    async def update_cout(self, key: str, value: int):
        await self.adm.update_many({}, {'$set': {f"{key}_threshold": value}})

db = Database(DATABASE_URI, DATABASE_NAME)
