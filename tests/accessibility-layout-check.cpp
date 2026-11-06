// Checks the accessible table of an item view against the real item layouter.
// The table methods are compiled from Dolphin's own source (methods.inc), so the
// check follows the code that runs. Every item must sit inside the declared
// table and be found again at its row and column.
#include "kitemviews/kitemmodelbase.h"
#include "kitemviews/private/kitemlistsizehintresolver.h"
#include "kitemviews/private/kitemlistviewlayouter.h"

#include <QGuiApplication>
#include <iostream>
#include <string>

KItemListSizeHintResolver::KItemListSizeHintResolver(const KItemListView *itemListView)
    : m_itemListView(itemListView)
    , m_logicalWidthHint(0)
    , m_minHeightHint(0)
    , m_needsResolving(false)
{
}
KItemListSizeHintResolver::~KItemListSizeHintResolver() = default;
QSizeF KItemListSizeHintResolver::sizeHint(int)
{
    return QSizeF(0, 0);
}

struct QAccessibleInterface {
    int index;
};

class FakeModel : public KItemModelBase
{
public:
    FakeModel(int items, int groupSize)
        : m_items(items)
        , m_groupSize(groupSize)
    {
    }
    int count() const override
    {
        return m_items;
    }
    QHash<QByteArray, QVariant> data(int) const override
    {
        return {};
    }
    QList<QPair<int, QVariant>> groups() const override
    {
        QList<QPair<int, QVariant>> result;
        if (m_groupSize > 0) {
            for (int i = 0; i < m_items; i += m_groupSize) {
                result.append({i, i});
            }
        }
        return result;
    }
    int m_items;
    int m_groupSize;
};

struct FakeView {
    KItemListViewLayouter *m_layouter;
    const KItemModelBase *m_model;
    const KItemModelBase *model() const
    {
        return m_model;
    }
};

struct KItemListViewAccessible {
    FakeView data;
    const FakeView *view() const
    {
        return &data;
    }
    QAccessibleInterface *accessibleDelegate(int index) const
    {
        if (index < 0 || index >= view()->model()->count()) {
            return nullptr;
        }
        return new QAccessibleInterface{index};
    }
    QAccessibleInterface *cellAt(int row, int column) const;
    int columnCount() const;
    int rowCount() const;
};

#include "methods.inc"

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    int failures = 0;
    int layouts = 0;
    for (Qt::Orientation orientation : {Qt::Vertical, Qt::Horizontal}) {
        for (int groupSize : {0, 1, 3}) {
            for (int items : {0, 1, 2, 3, 7, 20, 50}) {
                for (int width : {100, 300, 900}) {
                    FakeModel model(items, groupSize);
                    model.setGroupedSorting(groupSize > 0);
                    KItemListSizeHintResolver resolver(nullptr);
                    KItemListViewLayouter layouter(&resolver);
                    layouter.setScrollOrientation(orientation);
                    layouter.setItemSize(QSizeF(100, 80));
                    layouter.setItemMargin(QSizeF(4, 4));
                    layouter.setGroupHeaderHeight(20);
                    layouter.setGroupHeaderMargin(8);
                    layouter.setModel(&model);
                    layouter.setSize(QSizeF(width, 400));
                    const KItemListViewAccessible table{{&layouter, &model}};
                    ++layouts;

                    std::string problem;
                    const int rows = table.rowCount();
                    const int columns = table.columnCount();
                    int found = 0;
                    for (int row = 0; row < rows; ++row) {
                        for (int column = 0; column < columns; ++column) {
                            const QAccessibleInterface *cell = table.cellAt(row, column);
                            if (!cell) {
                                continue;
                            }
                            ++found;
                            if (layouter.itemRow(cell->index) != row || layouter.itemColumn(cell->index) != column) {
                                problem = "cell found at a different position";
                            }
                        }
                    }
                    if (found != items) {
                        problem = "found " + std::to_string(found) + " cells";
                    }
                    for (int i = 0; i < items; ++i) {
                        const int row = layouter.itemRow(i);
                        const int column = layouter.itemColumn(i);
                        if (row < 0 || row >= rows || column < 0 || column >= columns) {
                            problem = "item " + std::to_string(i) + " at row " + std::to_string(row) + ", column "
                                + std::to_string(column) + " outside the declared table";
                            break;
                        }
                    }
                    // Positions outside the table must give nothing instead of a wrong cell.
                    if (table.cellAt(-1, 0) || table.cellAt(0, -1) || table.cellAt(rows, 0) || table.cellAt(0, columns)
                        || table.cellAt(1000, 1000)) {
                        problem = "a position outside the table returned a cell";
                    }
                    if (!problem.empty()) {
                        ++failures;
                        std::cout << (orientation == Qt::Vertical ? "vertical" : "horizontal") << " group=" << groupSize << " items=" << items
                                  << " width=" << width << " table " << rows << "x" << columns << ": " << problem << "\n";
                    }
                }
            }
        }
    }
    std::cout << layouts << " layouts, " << failures << " failures\n";
    return failures ? 1 : 0;
}
