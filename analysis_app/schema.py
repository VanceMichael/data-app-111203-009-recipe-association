FIELDS = {'observation_id': 'str', 'lot': 'str', 'plant': 'str', 'month': 'int', 'items': 'str', 'yield_rate': 'float', 'size': 'int', 'recipe_version': 'str'}
REQUIRED = ['observation_id', 'lot', 'plant', 'yield_rate']
ENTITY = 'lot'
GROUP = 'plant'
MEASURE = 'yield_rate'
PRODUCT = 'recipe-association'
UNIT = '比例'
