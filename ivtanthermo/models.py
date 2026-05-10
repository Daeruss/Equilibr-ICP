# This is an auto-generated Django model module.
# You'll have to do the following manually to clean this up:
#   * Rearrange models' order
#   * Make sure each model has one field with primary_key=True
#   * Make sure each ForeignKey and OneToOneField has `on_delete` set to the desired behavior
#   * Remove `managed = False` lines if you wish to allow Django to create, modify, and delete the table
# Feel free to rename the models, but don't rename db_table values or field names.
from django.contrib.postgres.fields import ArrayField
from django.db import models


class AclGroup(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(unique=True, max_length=180)
    roles = models.TextField(db_comment='(DC2Type:array)')

    class Meta:
        managed = False
        db_table = 'acl_group'


class AclUser(models.Model):
    id = models.IntegerField(primary_key=True)
    username = models.CharField(max_length=180)
    username_canonical = models.CharField(unique=True, max_length=180)
    email = models.CharField(max_length=180)
    email_canonical = models.CharField(unique=True, max_length=180)
    enabled = models.BooleanField()
    salt = models.CharField(max_length=255, blank=True, null=True)
    password = models.CharField(max_length=255)
    last_login = models.DateTimeField(blank=True, null=True)
    confirmation_token = models.CharField(unique=True, max_length=180, blank=True, null=True)
    password_requested_at = models.DateTimeField(blank=True, null=True)
    roles = models.TextField(db_comment='(DC2Type:array)')
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()
    date_of_birth = models.DateTimeField(blank=True, null=True)
    firstname = models.CharField(max_length=64, blank=True, null=True)
    lastname = models.CharField(max_length=64, blank=True, null=True)
    website = models.CharField(max_length=64, blank=True, null=True)
    biography = models.CharField(max_length=1000, blank=True, null=True)
    gender = models.CharField(max_length=1, blank=True, null=True)
    locale = models.CharField(max_length=8, blank=True, null=True)
    timezone = models.CharField(max_length=64, blank=True, null=True)
    phone = models.CharField(max_length=64, blank=True, null=True)
    facebook_uid = models.CharField(max_length=255, blank=True, null=True)
    facebook_name = models.CharField(max_length=255, blank=True, null=True)
    facebook_data = models.TextField(blank=True, null=True, db_comment='(DC2Type:json)')
    twitter_uid = models.CharField(max_length=255, blank=True, null=True)
    twitter_name = models.CharField(max_length=255, blank=True, null=True)
    twitter_data = models.TextField(blank=True, null=True, db_comment='(DC2Type:json)')
    gplus_uid = models.CharField(max_length=255, blank=True, null=True)
    gplus_name = models.CharField(max_length=255, blank=True, null=True)
    gplus_data = models.TextField(blank=True, null=True, db_comment='(DC2Type:json)')
    token = models.CharField(max_length=255, blank=True, null=True)
    two_step_code = models.CharField(max_length=255, blank=True, null=True)
    middlename = models.CharField(max_length=64, blank=True, null=True)
    organization = models.ForeignKey('DacOrganization', models.DO_NOTHING, blank=True, null=True)
    firstname_ru = models.CharField(max_length=64, blank=True, null=True)
    lastname_ru = models.CharField(max_length=64, blank=True, null=True)
    middlename_ru = models.CharField(max_length=64, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'acl_user'


class AclUserGroup(models.Model):
    pk = models.CompositePrimaryKey('user_id', 'group_id')
    user = models.ForeignKey(AclUser, models.DO_NOTHING)
    group = models.ForeignKey(AclGroup, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'acl_user_group'


class Approx(models.Model):
    id = models.IntegerField(primary_key=True)
    label = models.CharField(unique=True, max_length=32, db_comment='Текстовый идентификатор функции, служит для поиска процедуры расчета в программах обработки данных')
    formula = models.TextField(blank=True, null=True, db_comment='Вид зависимости, коэффициенты обозначаются символами A, B, ...')
    num_coef = models.SmallIntegerField(db_comment='Количество коэффициентов')
    name_rus = models.TextField(blank=True, null=True, db_comment='Описание на русском языке')
    name_eng = models.TextField(blank=True, null=True, db_comment='Описание на английском языке')

    class Meta:
        managed = False
        db_table = 'approx'
        db_table_comment = 'Параметры аппроксимирующей функции для описания зависимости'


class Atom(models.Model):
    id = models.IntegerField(primary_key=True)
    charge = models.SmallIntegerField(db_comment='Заряд ядра (атомный номер), -1 для электрона')
    isotope = models.BooleanField(db_comment='= FALSE для естественного изотопного состава')
    symbol = models.CharField(max_length=16, db_comment='Международный символ химического элемента или обозначение изотопа')
    mass_num = models.SmallIntegerField(blank=True, null=True, db_comment='Атомная масса чистого изотопа, amu')

    class Meta:
        managed = False
        db_table = 'atom'
        db_table_comment = 'Атомы и их изотопы'


class Author(models.Model):
    id = models.IntegerField(primary_key=True)
    lastname = models.TextField(db_comment='Фамилия')
    initials = models.TextField(blank=True, null=True, db_comment='Инициалы')

    class Meta:
        managed = False
        db_table = 'author'
        db_table_comment = 'Авторы публикаций'


class BibAuthorRef(models.Model):
    id = models.IntegerField(primary_key=True)
    bib = models.ForeignKey('Bibliography', models.DO_NOTHING, db_comment='Идентификатор публикации')
    author = models.ForeignKey(Author, models.DO_NOTHING, db_comment='Идентификатор автора')
    pos = models.SmallIntegerField(blank=True, null=True, db_comment='Позиция в списке авторов')

    class Meta:
        managed = False
        db_table = 'bib_author_ref'
        db_table_comment = 'Участие авторов в публикациях (таблица связи)'


class BibPropRef(models.Model):
    id = models.IntegerField(primary_key=True)
    bib = models.ForeignKey('Bibliography', models.DO_NOTHING, db_comment='Идентификатор публикации')
    substprop = models.ForeignKey('Substprop', models.DO_NOTHING, db_comment='Идентификатор свойства')
    formula = models.TextField(blank=True, null=True, db_comment='Формула вещества (в произвольном формате)')

    class Meta:
        managed = False
        db_table = 'bib_prop_ref'
        db_table_comment = 'Таблица связи публикаций и отраженных в них свойств веществ'


class Bibcard(models.Model):
    id = models.IntegerField(primary_key=True, db_comment='Первичный ключ')
    label = models.TextField(db_comment='Наименование файла')
    section = models.CharField(max_length=16, db_comment='Секция, что-то типа местоположения')
    path = models.TextField(db_comment='Путь к файлу относительно каталога bib_cards')
    suggest_substance = models.TextField(blank=True, null=True, db_comment='Предлагаемые вещества')
    suggest_atom = models.TextField(blank=True, null=True, db_comment='Предлагаемые атомы')
    deleted = models.BooleanField(db_comment='Удален')
    note = models.TextField(blank=True, null=True)
    tags = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'bibcard'


class BibcardSubstanceRef(models.Model):
    pk = models.CompositePrimaryKey('bib_card_id', 'substance_id')
    bib_card = models.ForeignKey(Bibcard, models.DO_NOTHING, db_comment='Идентификатор карточки')
    substance = models.ForeignKey('Substance', models.DO_NOTHING, db_comment='Идентификатор вещества')

    class Meta:
        managed = False
        db_table = 'bibcard_substance_ref'


class Bibliography(models.Model):
    id = models.IntegerField(primary_key=True)
    label = models.CharField(unique=True, max_length=32, db_comment='Идентификатор BiBTeX, который может использовать в комментариях в формате \\cite{label}.')
    bibtype = models.ForeignKey('Bibtype', models.DO_NOTHING, db_comment='Идентификатор типа публикации')
    title = models.TextField(blank=True, null=True, db_comment='Название статьи или книги')
    journal = models.TextField(blank=True, null=True, db_comment='Название журнала')
    year = models.SmallIntegerField(blank=True, null=True, db_comment='Год издания')
    volume = models.CharField(max_length=32, blank=True, null=True, db_comment='Том')
    issue = models.CharField(max_length=32, blank=True, null=True, db_comment='Номер, выпуск')
    pages = models.CharField(max_length=32, blank=True, null=True, db_comment='Страница или диапазон страниц')
    publisher = models.TextField(blank=True, null=True, db_comment='Издательство (для книг и сборников)')
    booktitle = models.TextField(blank=True, null=True, db_comment='Название книги или сборника')
    institution = models.TextField(blank=True, null=True, db_comment='Название организации (для отчета)')
    address = models.TextField(blank=True, null=True, db_comment='Адрес издательства')
    editors = models.TextField(blank=True, null=True, db_comment='Редакторы')
    note = models.TextField(blank=True, null=True, db_comment='Комментарий для пользователей')
    doi = models.TextField(blank=True, null=True, db_comment='Идентификатор DOI')
    link = models.TextField(blank=True, null=True, db_comment='Ссылка на публикацию в сети Интернет')
    abstract = models.TextField(blank=True, null=True, db_comment='Аннотация')
    srcdata = models.TextField(blank=True, null=True, db_comment='Текст статьи')
    lang = models.CharField(max_length=2, blank=True, null=True, db_comment='Язык публикации')
    original_label = models.TextField(blank=True, null=True, db_comment='Идентификатор статьи, использованный при импорте публикации из внешней библиографической базы')
    expert_note = models.TextField(blank=True, null=True, db_comment='Комментарий для экспертов')

    class Meta:
        managed = False
        db_table = 'bibliography'
        db_table_comment = 'Библиографические источники'


class Bibtype(models.Model):
    id = models.IntegerField(primary_key=True)
    bibtex_type = models.CharField(max_length=16, db_comment='Идентификатор типа публикации в BiBTeX (article, book, inbook, inproceedings, techreport)')
    desc_rus = models.TextField(blank=True, null=True, db_comment='Наименование типа публикации на русском языке')
    desc_eng = models.TextField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'bibtype'
        db_table_comment = 'Типы библиографических ссылок'


class Comment(models.Model):
    id = models.IntegerField(primary_key=True)
    user_id = models.IntegerField(db_comment='Идентификатор пользователя')
    datainfo = models.ForeignKey('Datainfo', models.DO_NOTHING, db_comment='Идентификатор блока данных')
    created = models.DateTimeField(db_comment='Дата и время создания')
    note = models.TextField(blank=True, null=True, db_comment='Содержимое комментария')

    class Meta:
        managed = False
        db_table = 'comment'
        db_table_comment = 'Комментарии пользователей'


class CondPhase(models.Model):
    id = models.IntegerField(primary_key=True)
    crystal_symmetry = models.ForeignKey('CrystalSymmetry', models.DO_NOTHING, blank=True, null=True, db_comment='Идентификтор группы симметрии')
    label = models.CharField(max_length=64, db_comment='Краткое название фазы')
    note_eng = models.TextField(blank=True, null=True, db_comment='Описание на английском языке')
    note_rus = models.TextField(blank=True, null=True, db_comment='Описание на русском языке')

    class Meta:
        managed = False
        db_table = 'cond_phase'
        db_table_comment = 'Фазы для конденсированных веществ'


class CrystalSymmetry(models.Model):
    id = models.IntegerField(primary_key=True)
    crystal_system = models.ForeignKey('CrystalSystem', models.DO_NOTHING, db_comment='Сингония')
    sym_class = models.CharField(max_length=64, blank=True, null=True, db_comment='Класс симметрии')
    code_fyod = models.CharField(max_length=64, blank=True, null=True, db_comment='Пространственная группа')
    code_schon = models.CharField(max_length=64, blank=True, null=True)
    code_html = models.TextField(blank=True, null=True, db_comment='HTML код для отображения пространственной группы')

    class Meta:
        managed = False
        db_table = 'crystal_symmetry'
        db_table_comment = 'Группы симметрии для кристаллических фаз'


class CrystalSystem(models.Model):
    id = models.IntegerField(primary_key=True)
    name_eng = models.CharField(max_length=64, blank=True, null=True, db_comment='Название на английском языке')
    name_rus = models.CharField(max_length=64, blank=True, null=True, db_comment='Название на русском языке')

    class Meta:
        managed = False
        db_table = 'crystal_system'
        db_table_comment = 'Сингонии для кристаллов'


class DacDataGroup(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    access_thermo = models.BooleanField()

    class Meta:
        managed = False
        db_table = 'dac_data_group'


class DacDataGroupSubstanceRef(models.Model):
    pk = models.CompositePrimaryKey('group_id', 'substance_id')
    group = models.ForeignKey(DacDataGroup, models.DO_NOTHING)
    substance_id = models.IntegerField(db_comment='первичный ключ')

    class Meta:
        managed = False
        db_table = 'dac_data_group_substance_ref'


class DacOrganization(models.Model):
    id = models.IntegerField(primary_key=True)
    name_ru = models.CharField(unique=True, max_length=64)
    name_en = models.CharField(unique=True, max_length=64)
    fullname_ru = models.CharField(max_length=255)
    fullname_en = models.CharField(max_length=255)
    address = models.CharField(max_length=512)
    contacts = models.CharField(max_length=512)
    about = models.TextField(blank=True, null=True)
    is_verified = models.BooleanField()

    class Meta:
        managed = False
        db_table = 'dac_organization'


class DacOrganizationDataGroupRef(models.Model):
    pk = models.CompositePrimaryKey('group_id', 'organization_id')
    group = models.ForeignKey(DacDataGroup, models.DO_NOTHING)
    organization = models.ForeignKey(DacOrganization, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'dac_organization_data_group_ref'


class DacUserDataGroupRef(models.Model):
    pk = models.CompositePrimaryKey('group_id', 'user_id')
    group = models.ForeignKey(DacDataGroup, models.DO_NOTHING)
    user = models.ForeignKey(AclUser, models.DO_NOTHING)

    class Meta:
        managed = False
        db_table = 'dac_user_data_group_ref'


class DataBibRef(models.Model):
    id = models.IntegerField(primary_key=True)
    datainfo = models.ForeignKey('Datainfo', models.DO_NOTHING, db_comment='Идентификатор набора данных')
    bib = models.ForeignKey(Bibliography, models.DO_NOTHING, db_comment='Идентификатор публикации')

    class Meta:
        managed = False
        db_table = 'data_bib_ref'
        db_table_comment = 'Публикации, относящиеся к наборам данных (таблица связей)'


class DataGroup(models.Model):
    id = models.IntegerField(primary_key=True)
    desc_rus = models.TextField(blank=True, null=True, db_comment='Описание группы на русском языке')
    desc_eng = models.TextField(blank=True, null=True, db_comment='Описание группы на английском языке')

    class Meta:
        managed = False
        db_table = 'data_group'
        db_table_comment = 'Группа ресурсов, описывающая множество наборов данных к которым пользователь может получить доступ'


class DataGroupRef(models.Model):
    id = models.IntegerField(primary_key=True)
    datainfo = models.ForeignKey('Datainfo', models.DO_NOTHING, db_comment='Идентификатор набора данных')
    group = models.ForeignKey(DataGroup, models.DO_NOTHING, db_comment='Идентификатор группы ресурсов')

    class Meta:
        managed = False
        db_table = 'data_group_ref'
        db_table_comment = 'Принадлежность наборов данных группам ресурсов (таблица связи)'


class Datainfo(models.Model):
    id = models.IntegerField(primary_key=True)
    contributor_id = models.IntegerField(blank=True, null=True, db_comment='Идентификатор эксперта, добавившего данные')
    release_no = models.IntegerField(blank=True, null=True, db_comment='Номер релиза. Имеет значение >0 для данных, имеющих или имевших ранее статус рекомендуемых для пользователей.')
    created = models.DateTimeField(db_comment='Дата создания записи')
    modified = models.DateTimeField(db_comment='Дата и время последнего изменения данных')
    note_ru = models.TextField(blank=True, null=True, db_comment='Комментарии эксперта на русском языке')
    note_en = models.TextField(blank=True, null=True, db_comment='Комментарии эксперта на английском языке')
    revision_note = models.TextField(blank=True, null=True, db_comment='Описание изменения (информация для экспертов, не выводится пользователям)')

    class Meta:
        managed = False
        db_table = 'datainfo'
        db_table_comment = 'Дополнительные сведения о блоке данных'


class Dimension(models.Model):
    id = models.IntegerField(primary_key=True)
    quantity = models.ForeignKey('Quantity', models.DO_NOTHING, db_comment='Идентификатор величины')
    name_eng = models.TextField(blank=True, null=True, db_comment='Название размерности на английском языке')
    name_rus = models.TextField(blank=True, null=True, db_comment='Название размерности на русском языке')
    ratio = models.FloatField(db_comment='Коэффициент пересчета, равен 1.0 для основной единицы')

    class Meta:
        managed = False
        db_table = 'dimension'
        db_table_comment = 'Размерности физических величин'


class GibbsCoef(models.Model):
    id = models.IntegerField(primary_key=True)
    thermo = models.ForeignKey('Thermo', models.DO_NOTHING, db_comment='Идентификатор набора термодинамических данных')
    approx = models.ForeignKey(Approx, models.DO_NOTHING, db_comment='Идентификатор типа аппроксимации')
    tmin = models.FloatField(blank=True, null=True, db_comment='Начальная температура, К')
    tmax = models.FloatField(blank=True, null=True, db_comment='Конечная температура, К')
    data = ArrayField(models.FloatField(), blank=True, null=True, db_comment='?????? ????????????? ???????????????? ???????')
    cond_phase = models.ForeignKey(CondPhase, models.DO_NOTHING, blank=True, null=True, db_comment='Идентификатор фазы для кристаллических веществ')

    class Meta:
        managed = False
        db_table = 'gibbs_coef'
        db_table_comment = 'Параметры аппроксимации для зависимости приведенной энергии Гиббса от температуры в заданном интервале температур'


class GlobalConstants(models.Model):
    id = models.IntegerField(primary_key=True)
    label = models.CharField(unique=True, max_length=32, db_comment='Сокращенное название величины')
    val = models.FloatField(db_comment='Значение')
    error = models.FloatField(blank=True, null=True, db_comment='Абсолютная погрешность')

    class Meta:
        managed = False
        db_table = 'global_constants'
        db_table_comment = 'Значения фундаментальных и других констант, принятых в базе'


class IvtThermoData(models.Model):
    id = models.IntegerField(primary_key=True)
    substance_id = models.IntegerField(db_comment='Идентификатор вещества')
    datainfo_id = models.IntegerField(unique=True, db_comment='Идентификатор описателя набора данных')
    recommended = models.BooleanField(db_comment='TRUE, если набор данных является рекомендуемым. Эти данные предоставляется пользователям по умолчанию.')
    dfh0 = models.FloatField(blank=True, null=True, db_comment='Энтальпия образования при T=0K, ΔfH(0), Дж/моль')
    dfh298 = models.FloatField(blank=True, null=True, db_comment='Энтальпия образования при T=298.15K, ΔfH(298.15), Дж/моль')
    cp298 = models.FloatField(blank=True, null=True, db_comment='Изобарная теплоемкость при T=298.15K, Дж/моль/К')
    s298 = models.FloatField(blank=True, null=True, db_comment='Энтропия при T=298.15K, Дж/моль')
    dh298 = models.FloatField(blank=True, null=True, db_comment='Приращение энтальпии H(298.15) - H(0), Дж/моль')
    drh298 = models.FloatField(blank=True, null=True, db_comment='Энтальпия реакции образования ΔrH(0), Дж/моль')
    drh298_err = models.FloatField(blank=True, null=True, db_comment='Абсолютная погрешность энтальпии реакции образования ΔrH(0), Дж/моль')
    f3000_err = models.FloatField(blank=True, null=True, db_comment='Абсолютная погрешность приведенной энергии гиббса при 3000К, Дж/моль')
    acc_class = models.CharField(max_length=16, blank=True, null=True, db_comment='Класс точности в обозначениях системы ИВТАНТЕРМО')
    gibbs_data = models.JSONField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'ivt_thermo_data'
        db_table_comment = 'Термодинамические и термохимические свойства веществ'


class MigrationVersions(models.Model):
    version = models.CharField(primary_key=True, max_length=14)
    executed_at = models.DateTimeField(db_comment='(DC2Type:datetime_immutable)')

    class Meta:
        managed = False
        db_table = 'migration_versions'


class Molecule(models.Model):
    id = models.IntegerField(primary_key=True)
    formula = models.CharField(unique=True, max_length=64, db_comment='Химическая формула вещества')
    num_atoms = models.SmallIntegerField(db_comment='Количество атомов в молекуле')
    ion_charge = models.SmallIntegerField(db_comment='Заряд иона (=0 для атомов)')

    class Meta:
        managed = False
        db_table = 'molecule'
        db_table_comment = 'Молекулы (индивидуальные вещества)'


class MoleculeAtomRef(models.Model):
    id = models.IntegerField(primary_key=True)
    atom = models.ForeignKey(Atom, models.DO_NOTHING, db_comment='Идентификатор атома')
    molecule = models.ForeignKey(Molecule, models.DO_NOTHING, db_comment='Идентификатор молекулы')
    num_elements = models.FloatField(db_comment='Число атомов в молекуле (может быть дробным для нестехиометрических соединений)')

    class Meta:
        managed = False
        db_table = 'molecule_atom_ref'
        db_table_comment = 'Содержание атомов в молекулах (таблица связи)'


class MoleculeProp(models.Model):
    id = models.IntegerField(primary_key=True)
    molecule = models.ForeignKey(Molecule, models.DO_NOTHING, db_comment='Идентификатор молекулы')
    datainfo = models.OneToOneField(Datainfo, models.DO_NOTHING, db_comment='Идентификатор описателя набора данных')
    recommended = models.BooleanField(db_comment='TRUE, если набор данных является рекомендуемым. Эти данные предоставляется пользователям по умолчанию.')
    mass = models.FloatField(blank=True, null=True, db_comment='Молярная масса, г/моль')
    nucl_entropy = models.FloatField(blank=True, null=True, db_comment='Ядерная составляющая энтропии')
    crit_temp = models.FloatField(blank=True, null=True, db_comment='Критическая температура, К')
    crit_press = models.FloatField(blank=True, null=True, db_comment='Критическое давление, Па')
    crit_volume = models.FloatField(blank=True, null=True, db_comment='Критический объем, м³')

    class Meta:
        managed = False
        db_table = 'molecule_prop'
        db_table_comment = 'Физические и химические свойства молекул'


class Phase(models.Model):
    id = models.IntegerField(primary_key=True)
    label = models.CharField(unique=True, max_length=32, db_comment='Краткое обозначение, соответствует системе ИВТАНТЕРМО для Windows (c, l, cr, g, am, gl).')
    name_ru = models.TextField(blank=True, null=True, db_comment='Описание на русском языке')
    name_en = models.TextField(blank=True, null=True, db_comment='Описание на английском языке')

    class Meta:
        managed = False
        db_table = 'phase'
        db_table_comment = 'Виды фазовых состояний или конформаций веществ'


class Quantity(models.Model):
    id = models.IntegerField(primary_key=True)
    label = models.CharField(unique=True, max_length=32, db_comment='Сокращенне название величины (индекс)')
    symbol = models.CharField(max_length=32, blank=True, null=True, db_comment='Обозначение величины')

    class Meta:
        managed = False
        db_table = 'quantity'
        db_table_comment = 'Физические величины, для которых допускается использование различных размерностей'


class Substance(models.Model):
    id = models.IntegerField(primary_key=True)
    molecule = models.ForeignKey(Molecule, models.DO_NOTHING, db_comment='Идентификатор молекулы')
    phase = models.ForeignKey(Phase, models.DO_NOTHING, db_comment='Основная фаза вещества')
    cas = models.CharField(max_length=12, blank=True, null=True, db_comment='Регистрационный номер CAS')
    inchi = models.CharField(max_length=255, blank=True, null=True, db_comment='Идентификатор вещества: IUPAC International Chemical Identifier (InChi)')
    isomeric_form = models.TextField(blank=True, null=True, db_comment='Изомерная форма')
    modification = models.CharField(max_length=255, blank=True, null=True, db_comment='Модификация')
    struct = models.TextField(blank=True, null=True, db_comment='Данные о структуре молекулы')
    tsiv_table_no = models.SmallIntegerField(blank=True, null=True, db_comment='Номер таблицы в БД ИВТАНТЕРМО (Соответствует изданию ТСИВ)')
    label = models.CharField(unique=True, max_length=255, db_comment='Краткое уникальное название вещества')
    reaction = models.CharField(max_length=255, blank=True, null=True, db_comment='Реакция образования')

    class Meta:
        managed = False
        db_table = 'substance'
        db_table_comment = 'Индивидуальные вещества в определенных фазовых состояниях'


class SubstanceGroup(models.Model):
    id = models.IntegerField(primary_key=True)
    name_rus = models.TextField(blank=True, null=True, db_comment='Название группы на русском языке')
    name_eng = models.TextField(blank=True, null=True, db_comment='Название группы на английском языке')

    class Meta:
        managed = False
        db_table = 'substance_group'
        db_table_comment = 'Группы индивидуальных веществ'


class SubstanceGroupRef(models.Model):
    id = models.IntegerField(primary_key=True)
    substance = models.ForeignKey(Substance, models.DO_NOTHING, db_comment='Идентификатор вещества')
    substance_group = models.ForeignKey(SubstanceGroup, models.DO_NOTHING, db_comment='Идентификатор группы веществ')

    class Meta:
        managed = False
        db_table = 'substance_group_ref'
        db_table_comment = 'Вхождение веществ в группы (таблица связей)'


class SubstanceName(models.Model):
    id = models.IntegerField(primary_key=True)
    substance = models.ForeignKey(Substance, models.DO_NOTHING, db_comment='Идентификатор вещества')
    name_en = models.CharField(max_length=255, db_comment='Название вещества на английском языке')
    name_ru = models.CharField(max_length=255, blank=True, null=True, db_comment='Название вещества на русском языке')
    default_name = models.BooleanField(db_comment='=TRUE для имени по умолчанию')

    class Meta:
        managed = False
        db_table = 'substance_name'
        db_table_comment = 'Названия веществ, включая альтернативные названия'


class Substprop(models.Model):
    id = models.IntegerField(primary_key=True)
    desc_rus = models.TextField(blank=True, null=True, db_comment='Описание свойства на русском языке')
    desc_eng = models.TextField(blank=True, null=True, db_comment='Описание свйоства на английском языке')
    bib_code = models.TextField(blank=True, null=True, db_comment='Шифр из библиографической системы "BIBIVTAN" в формате "PROPTY/CODE"')

    class Meta:
        managed = False
        db_table = 'substprop'
        db_table_comment = 'Характеристики веществ, измеренные или расчитанные в публикации'


class Thermo(models.Model):
    id = models.IntegerField(primary_key=True)
    substance = models.ForeignKey(Substance, models.DO_NOTHING, db_comment='Идентификатор вещества')
    datainfo = models.OneToOneField(Datainfo, models.DO_NOTHING, db_comment='Идентификатор описателя набора данных')
    recommended = models.BooleanField(db_comment='TRUE, если набор данных является рекомендуемым. Эти данные предоставляется пользователям по умолчанию.')
    dfh0 = models.FloatField(blank=True, null=True, db_comment='Энтальпия образования при T=0K, ΔfH(0), Дж/моль')
    dfh298 = models.FloatField(blank=True, null=True, db_comment='Энтальпия образования при T=298.15K, ΔfH(298.15), Дж/моль')
    cp298 = models.FloatField(blank=True, null=True, db_comment='Изобарная теплоемкость при T=298.15K, Дж/моль/К')
    s298 = models.FloatField(blank=True, null=True, db_comment='Энтропия при T=298.15K, Дж/моль')
    dh298 = models.FloatField(blank=True, null=True, db_comment='Приращение энтальпии H(298.15) - H(0), Дж/моль')
    drh298 = models.FloatField(blank=True, null=True, db_comment='Энтальпия реакции образования ΔrH(0), Дж/моль')
    drh298_err = models.FloatField(blank=True, null=True, db_comment='Абсолютная погрешность энтальпии реакции образования ΔrH(0), Дж/моль')
    f3000_err = models.FloatField(blank=True, null=True, db_comment='Абсолютная погрешность приведенной энергии гиббса при 3000К, Дж/моль')
    acc_class = models.CharField(max_length=16, blank=True, null=True, db_comment='Класс точности в обозначениях системы ИВТАНТЕРМО')
    temperature = ArrayField(models.FloatField(), blank=True, null=True, db_comment='?????? ?????????? ??? ???????? ???????? ????????????????? ???????, ?')
    heatcapacity = ArrayField(models.FloatField(), blank=True, null=True, db_comment='?????? ???????? ????????? ????????????, Cp(T), ??/????/?')
    gibbs = ArrayField(models.FloatField(), blank=True, null=True, db_comment='?????? ???????? ??????????? ??????? ??????, (T) = ?(T) - (H(T) - H(0))/T, ??/????/?')
    entropy = ArrayField(models.FloatField(), blank=True, null=True, db_comment='?????? ???????? ????????, S(T), ??/????/?')
    enthalpy = ArrayField(models.FloatField(), blank=True, null=True, db_comment='?????? ???????? ????????? ?????????, H(T) - H(0), ??/????')
    logkp = ArrayField(models.FloatField(), blank=True, null=True, db_comment='?????? ???????? ??????????? ????????? ????????? ?????????? ??????? ??????????? (??????????), log(Kp)')

    class Meta:
        managed = False
        db_table = 'thermo'
        db_table_comment = 'Термодинамические и термохимические свойства веществ'

class SubstanceCharge(models.Model):
    substance_id = models.IntegerField(primary_key=True)
    charge = models.SmallIntegerField(db_index=True)
    source_label = models.CharField(max_length=255)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "substance_charge"
        ordering = ("substance_id",)

    def __str__(self):
        return f"{self.substance_id}: {self.charge}"
