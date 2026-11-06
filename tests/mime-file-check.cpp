#include <QCoreApplication>
#include <QMimeDatabase>
#include <QTextStream>

int main(int argc, char **argv)
{
    QCoreApplication app(argc, argv);
    QTextStream output(stdout);
    QMimeDatabase database;
    for (const auto &path : app.arguments().mid(1)) {
        output << path << '\t' << database.mimeTypeForFile(path).name() << '\n';
    }
}
