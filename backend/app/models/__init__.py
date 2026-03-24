"""
LeakSight V1 — Model Registry

All SQLAlchemy models must be imported here so that Alembic's
Base.metadata can detect them for migration autogeneration.
"""

from backend.app.models.tenant import Tenant, User, TenantSettings  # noqa: F401
from backend.app.models.raw import Document, RawParse  # noqa: F401
from backend.app.models.vendors import Vendor, VendorAlias  # noqa: F401
from backend.app.models.units import CanonicalUnit, UnitConversionFactor, FxRate  # noqa: F401
from backend.app.models.contracts import Contract, ContractVersion, ContractLineItem  # noqa: F401
from backend.app.models.invoices import Invoice, InvoiceLineItem  # noqa: F401
from backend.app.models.purchase_orders import PurchaseOrder, PoLineItem  # noqa: F401
from backend.app.models.grns import Grn, GrnLineItem  # noqa: F401
from backend.app.models.derived import (  # noqa: F401
    AnalysisRun,
    LeakageRecord,
    DocumentHash,
)
from backend.app.models.notifications import Notification  # noqa: F401
from backend.app.tools.contract_structuring.models import (  # noqa: F401
    ContractStructuringRun,
    ContractStructuringRunDocument,
    RawContractTable,
    ExtractedLineItem,
    ExtractedClause,
    ContractStructuringExport,
)
