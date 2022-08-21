from abc import ABCMeta, abstractmethod

class Strategy(object):
    """
    Стратегия определяет цену входа и выхода,
    создает событие "сигнал"
    """

    __metaclass__ = ABCMeta

    @abstractmethod
    def calculate_signals(self):
        """
        Provides the mechanisms to calculate the list of signals.
        """
        raise NotImplementedError("Should implement calculate_signals()")


class AvellanedaStoikov(Strategy):
    '''input -> market data event with best bid and best ask'''
    '''output -> signal event with bid ask quote prices '''

    def calculate_signals(self, event):
        '''event is market data event with best bid and best ask '''
        '''reads best bid and best ask from any source (event, local data storage, etc) '''
        best_bid = float(self.data_storage.best_bid_ask[event.market]['last_best_bid'])
        best_ask = float(self.data_storage.best_bid_ask[event.market]['last_best_ask'])

        #account
        '''reads account equity from any source (local data storage) '''
        account_equity = float(self.data_storage.account['total'])

        #positions
        '''reads positions data from any source (local data storage) '''
        current_inventory = 0
        for p in self.data_storage.positions:
            if event.market == p.market:
                if p.side == 'LONG':
                    current_inventory = float(p.usd_value)
                if p.side == 'SHORT':
                    current_inventory = - float(p.usd_value)

        if account_equity != 0:
            buy_quote, sell_quote, spread = self.avellaneda_stoikov_formula(best_ask, best_bid, current_inventory, account_equity, event.market)
            '''output -> signal event with bid ask quote prices '''
            self.create_signal_event(event.market, buy_quote, sell_quote)

    def avellaneda_stoikov_formula(self, best_ask, best_bid, current_inventory, account_equity, market):
        ''' target_inventory - inventory target based on our analytics '''
        target_inventory = self.calc_target_inventory()

        '''q - distance between current inventory(positions) and target inventory'''
        '''my implementation: q is calculated as a share of account balance
        needed to buy/sell to reach target inventoty
        strategy_price_shift_coef - значение определено подбором, в зависимости от стретагии
        значения 5-20'''

        q = (-target_inventory + current_inventory) / account_equity * self.settings['strategy_price_shift_coef']

        '''волатильность, значение по умолчанию - 2
        При значении 9 reservation price смещается на 1.5%
        Работа этого фактора до конца не ясна.

        upd: при высокой sigma мы не хотим увеличивать позицию
        и хотим быстрее ее закрыть,
        поэтому r_price смещается в сторону цели. '''
        sigma = self.read_sigma_value(market)


        ''' Гамма - риск фактор
        Повышение Гаммы сужает оптимальный спред и
        сдвигает reservation price чтобы быстрее достичь целевого портфеля

        Гамма хардкодится/задается пользователем. У меня считается в зависимости от левереджа.'''
        gamma = self.gamma_calculation(market)


        '''Плотность ордербуков / ликвидность.
        Очень сильно влияет на оптимальный спред.
        При к = 0.1, спред 14%, для совсем говна
        При к = 2 спред 1%, более-менее адекватное значение
        При к = 5 спред <0.5%, для какого-нибудь биткоина или эфира.'''
        k = self.read_k_value(market)

        mid_price = (best_ask + best_bid) / 2

        # Reserve price
        '''проблема старого рассчета r_price по формуле
        r_price = mid_price - q * gamma * sigma**2*self.time_func()
        состоит в тои что q это значение в пределах 1-2, оно не является % от цены,
        поэтому для разных рынков с разными ценами (АТОМ, BTC) получается разный результат

        Решение: считаем этот результат не абсолютным значением, а % от цены'''
        shift = q * gamma * sigma**2*self.time_func() / 100

        '''reservation price - наша цена с учетом смещения из-за наших таргетов и тд '''
        r_price = mid_price - mid_price * shift

        '''Reserve spread / optimal spread
        спред, который сильно зависит от риск фактора и плотности ордербуков'''
        r_spread = 2 / gamma * math.log(1+gamma/k)

        '''r_spread должен быть в единицах tick_size '''
        r_spread = self.get_tick_size(market) * r_spread

        ''' optimal quotes '''
        ask_price = r_price + r_spread/2
        bid_price = r_price - r_spread/2

        optimal_spread = r_spread / mid_price * 100


        print('current_inventory:' , round(current_inventory, 2), '\n',
        'target_inventory:', round(target_inventory, 2), '\n',
        'q(distance to target inventory):', round(q, 2), '\n',
        ' mid_price:', round(mid_price, 2), '\n',
        ' gamma(risk):', round(gamma, 2),  '\n',
        ' vol(sigma):', round(sigma, 2), '\n',
        ' r_price:', round(r_price, 2),  '\n',
        ' k(orderbook liquidity):', round(k, 2), '\n',
        ' r_spread:', round(r_spread, 2),  '\n',
        ' optimal_spread:', round(optimal_spread, 2),'%',  '\n',
        ' bid_price:', round(bid_price, 2), '\n',
        ' ask_price:', round(ask_price, 2)
        )

        '''выводим смещение цены от средней, удобно для тестов '''
        shift_pct = (r_price - mid_price) / mid_price * 100
        print('shift_pct is ', shift_pct, '%', '\n')

        return bid_price, ask_price, r_spread

    def create_signal_event(market, buy_quote, sell_quote):
        raise NotImplementedError("Should implement create_signal_event()")

    def calc_target_inventory():
        raise NotImplementedError("Should implement calc_target_inventory()")

    def read_sigma_value():
        raise NotImplementedError("Should implement read_sigma_value()")

    def gamma_calculation():
        raise NotImplementedError("Should implement gamma_calculation()")

    def read_k_value():
        raise NotImplementedError("Should implement read_k_value()")

    def time_func(self):
        '''функция для алгоритма ММ Авелланеда Стойков
        определяет время до конца торговой сессии(это нужно для лучшей работы алгоритма)
        базовый вариант берет сегодняшнюю дату и считает время 0:00 началом
        тестовое время работы алгоритма = 24 часа
        завтрашняя дата 0:00 считается временем когда нужно закрыть позиции

        time_func = (0+dt*n)
        dt - количество секунд между началом работы и концом
        dt = 1 / difference
        difference - время конца работы минус время начала работы
        n - текущая секунда'''

        start_time = datetime.now()
        start_date = datetime.date(start_time)
        start_dt = datetime(
                year=start_date.year,
                month=start_date.month,
                day=start_date.day
             )
        start_timestamp = int(start_dt.timestamp())

        target_time = start_time + timedelta(hours = 24)
        finish_dt = datetime(
                year=target_time.year,
                month=target_time.month,
                day=target_time.day
             )
        finish_timestamp = int(finish_dt.timestamp())

        difference = finish_timestamp - start_timestamp
        dt = 1 / difference

        current_time_timestamp = start_time.timestamp()
        n = current_time_timestamp - start_timestamp

        time_func = (0+dt*n)

        return time_func
