import aioconsole
import sys


class MessengerCLI:
    PROMPT = '\r(messenger)~# '

    def __init__(self, messenger_server):
        self.messenger_server = messenger_server


    @staticmethod
    def create_table(title, columns: list, items: list) -> str:
        # Calculate the maximum width for each column
        col_widths = [len(col) for col in columns]
        for item in items:
            for idx, col in enumerate(columns):
                col_widths[idx] = max(col_widths[idx], len(str(item.get(col, ''))) + 4)

        # Create the table header
        header = f"{title:^{sum(col_widths) + len(columns) - 1}}\n"
        header += ' '.join([f"{col:^{width}}" for col, width in zip(columns, col_widths)]) + '\n'
        header += ' '.join(['-' * width for width in col_widths]) + '\n'

        # Create the table rows
        rows = []
        for item in items:
            row = ' '.join([f"{str(item.get(col, '')):^{width}}" for col, width in zip(columns, col_widths)]) + '\n'
            rows.append(row)

        # Combine header and rows to form the table
        table = header + ''.join(rows)
        return table

    async def run(self):
        print('Welcome to the Messenger CLI, type exit or socks.')
        while True:
            user_input = await aioconsole.ainput(self.PROMPT)
            if not user_input.strip():
                continue
            user_input = user_input.strip()
            if user_input == 'exit':
                sys.exit(0)
            if user_input == 'socks':
                socks_servers = []
                for socks_server in self.messenger_server.socks_servers:
                    transport = 'HTTP' if socks_server.transport == 'http' else 'WS'
                    socks_servers.append({
                        'transport': transport,
                        'port': socks_server.port,
                        'client(s)': len(socks_server.clients),
                        'listening': not socks_server.is_stopped()
                    })
                print(self.create_table('SOCKS SERVERS', ['transport', 'port', 'client(s)', 'listening'], socks_servers))
