import javax.swing.*;
import javax.swing.event.DocumentEvent;
import javax.swing.event.DocumentListener;
import javax.swing.table.DefaultTableModel;
import javax.swing.event.ListSelectionEvent;
import javax.swing.table.TableRowSorter;
import java.awt.*;
import java.awt.event.ActionEvent;
import java.awt.event.KeyEvent;
import java.awt.event.ActionListener;
import java.io.*;
import java.util.Vector;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.Map;
import java.util.List;
import java.util.ArrayList;
import java.io.BufferedWriter;
import java.io.FileWriter;
import java.io.IOException;
import java.io.File;
import javax.swing.JOptionPane;
import javax.swing.table.TableColumn;
import javax.swing.table.JTableHeader;

import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;
import org.apache.commons.csv.CSVPrinter;

import org.apache.commons.io.output.AppendableOutputStream;



public class CSVGuiApp {
    private JFrame frame;
    private JTable table;
    private DefaultTableModel tableModel;
    private JTextField searchField;
    private JTextField[] inputFields;
    private final String[] columnNames = {
            "Part Name", "Library Ref", "Footprint Ref", "CreatedBy", "HelpURL",
            "Manufacturer 1", "Manufacturer 1 Part Number", "Vendor 1", "Vendor 1 Part Number",
            "Description", "Value", "Comment"
    };
    private String currentFileName = "";

    public CSVGuiApp() {
        frame = new JFrame("CSV Manager");
        frame.setDefaultCloseOperation(JFrame.EXIT_ON_CLOSE);
        frame.setLayout(new BorderLayout());

        // Table setup
        tableModel = new DefaultTableModel(columnNames, 0);
        table = new JTable(tableModel);
        frame.add(new JScrollPane(table), BorderLayout.CENTER);
        table.getSelectionModel().addListSelectionListener(e -> updateTextFields(e));

        // Disable table auto-editing, makes Ctrl+U work correctly
        table.putClientProperty("JTable.autoStartsEdit", Boolean.FALSE);

        // Search panel
        JPanel searchPanel = new JPanel(new BorderLayout());
        searchField = new JTextField();
        searchField.getDocument().addDocumentListener(new DocumentListener() {
            @Override
            public void insertUpdate(DocumentEvent e) {
                searchDatabase();
            }

            @Override
            public void removeUpdate(DocumentEvent e) {
                searchDatabase();
            }

            @Override
            public void changedUpdate(DocumentEvent e) {
                searchDatabase();
            }
        });
        searchPanel.add(new JLabel("Search: "), BorderLayout.WEST);
        searchPanel.add(searchField, BorderLayout.CENTER);
        frame.add(searchPanel, BorderLayout.NORTH);

        // Input panel for adding rows
        JPanel inputPanel = new JPanel(new GridLayout(columnNames.length + 1, 2));
        inputFields = new JTextField[columnNames.length];
        for (int i = 0; i < columnNames.length; i++) {
            inputPanel.add(new JLabel(columnNames[i] + ":"));
            inputFields[i] = new JTextField();
            inputPanel.add(inputFields[i]);
        }
        
        
        JButton addButton = new JButton("Add Row");
        inputPanel.add(addButton);
        frame.add(inputPanel, BorderLayout.SOUTH);

        JButton updateButton = new JButton("Update Row");
        inputPanel.add(updateButton);
        frame.add(inputPanel, BorderLayout.SOUTH);


        // Menu bar for file operations
        JMenuBar menuBar = new JMenuBar();
        JMenu fileMenu = new JMenu("File");
        JMenuItem openItem = new JMenuItem("Open CSV");
        JMenuItem saveItem = new JMenuItem("Save CSV");
        fileMenu.add(openItem);
        fileMenu.add(saveItem);
        menuBar.add(fileMenu);
        frame.setJMenuBar(menuBar);

        // ******************************************************************************************

        // Create the action for Ctrl+O
        Action openAction = new AbstractAction() {
            @Override
            public void actionPerformed(ActionEvent e) {
                // This is the subroutine that will run when Ctrl+O is pressed
                openCSV();
            }
        };
        // Map Ctrl+O to the openAction
        String ctrlO = "ctrl O";  // Key stroke for Ctrl+O
        InputMap inputMap1 = frame.getRootPane().getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW);
        ActionMap actionMap1 = frame.getRootPane().getActionMap();
        // Bind the action to Ctrl+O
        inputMap1.put(KeyStroke.getKeyStroke(KeyEvent.VK_O, KeyEvent.CTRL_DOWN_MASK), ctrlO);
        actionMap1.put(ctrlO, openAction);

        // ******************************************************************************************

        // ******************************************************************************************

        // Create the action for Ctrl+S
        Action saveAction = new AbstractAction() {
            @Override
            public void actionPerformed(ActionEvent e) {
                // This is the subroutine that will run when Ctrl+O is pressed
                saveCSV();
            }
        };
        // Map Ctrl+S to the saveAction
        String ctrlS = "ctrl S";  // Key stroke for Ctrl+S
        InputMap inputMap2 = frame.getRootPane().getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW);
        ActionMap actionMap2 = frame.getRootPane().getActionMap();
        // Bind the action to Ctrl+S
        inputMap2.put(KeyStroke.getKeyStroke(KeyEvent.VK_S, KeyEvent.CTRL_DOWN_MASK), ctrlS);
        actionMap2.put(ctrlS, saveAction);

        // ******************************************************************************************

        // ******************************************************************************************

        // Create the action for Ctrl+Q
        Action addRowAction = new AbstractAction() {
            @Override
            public void actionPerformed(ActionEvent e) {
                // This is the subroutine that will run when Ctrl+Q is pressed
                addRow();
            }
        };
        // Map Ctrl+Q to the saveAction
        String ctrlQ = "ctrl Q";  // Key stroke for Ctrl+Q
        InputMap inputMap3 = frame.getRootPane().getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW);
        ActionMap actionMap3 = frame.getRootPane().getActionMap();
        // Bind the action to Ctrl+Q
        inputMap3.put(KeyStroke.getKeyStroke(KeyEvent.VK_Q, KeyEvent.CTRL_DOWN_MASK), ctrlQ);
        actionMap3.put(ctrlQ, addRowAction);

        // ******************************************************************************************

        // ******************************************************************************************

        // Create the action for Ctrl+U
        Action updateRowAction = new AbstractAction() {
            @Override
            public void actionPerformed(ActionEvent e) {
                // This is the subroutine that will run when Ctrl+U is pressed
                updateRow();
            }
        };
        // Map Ctrl+U to the saveAction
        String ctrlU = "ctrl U";  // Key stroke for Ctrl+U
        InputMap inputMap4 = frame.getRootPane().getInputMap(JComponent.WHEN_IN_FOCUSED_WINDOW);
        ActionMap actionMap4 = frame.getRootPane().getActionMap();
        // Bind the action to Ctrl+U
        inputMap4.put(KeyStroke.getKeyStroke(KeyEvent.VK_U, KeyEvent.CTRL_DOWN_MASK), ctrlU);
        actionMap4.put(ctrlU, updateRowAction);

        // ******************************************************************************************



        // Action listeners
        openItem.addActionListener(e -> openCSV());
        saveItem.addActionListener(e -> saveCSV());
        addButton.addActionListener(e -> addRow());
        updateButton.addActionListener(e -> updateRow());

        frame.setExtendedState(JFrame.MAXIMIZED_BOTH); // Maximize the window
        frame.setVisible(true);

        openCSV("../components.csv");
        adjustColumnWidths();
        searchDatabase(); // Initialize the rowsorter just by calling this function
    }

    private void adjustColumnWidths() {
        JTableHeader tableHeader = table.getTableHeader();
        if (tableHeader == null) return;

        FontMetrics headerFontMetrics = tableHeader.getFontMetrics(tableHeader.getFont());

        for (int i = 0; i < table.getColumnCount(); i++) {
            TableColumn column = table.getColumnModel().getColumn(i);
            String headerValue = table.getColumnName(i);

            // Calculate the preferred width for the header
            int preferredWidth = headerFontMetrics.stringWidth(headerValue) + 10; // Add padding

            // Update the column's preferred width
            column.setPreferredWidth(preferredWidth);
        }
    }

    private void updateTextFields(ListSelectionEvent e) {
        if (!e.getValueIsAdjusting() && table.getSelectedRow() != -1) {
            // Get the selected row in the filtered view
            int selectedRow = table.getSelectedRow();

            // Convert the selected row index to the model index
            int modelRow = table.getRowSorter().convertRowIndexToModel(selectedRow);

            // Loop through the columns and update the text fields
            for (int i = 0; i < columnNames.length; i++) {
                String value = tableModel.getValueAt(modelRow, i).toString();
                inputFields[i].setText(value);
            }
        }
    }

    // private boolean openCSV() {
    //     JFileChooser fileChooser = new JFileChooser();
    //     if (fileChooser.showOpenDialog(frame) == JFileChooser.APPROVE_OPTION) {
    //         File file = fileChooser.getSelectedFile();
    //         return openCSV(file);
    //     }
    //     return false;
    // }

    private boolean openCSV() {
        FileDialog dialog = new FileDialog(frame, "Open CSV", FileDialog.LOAD);
        dialog.setVisible(true);

        String directory = dialog.getDirectory();
        String filename  = dialog.getFile();

        if (directory == null || filename == null) {
            return false; // user cancelled
        }

        File file = new File(directory, filename);
        return openCSV(file);
    }

    private boolean openCSV(String fileName) {
        File file = new File(fileName);
        if (!file.exists() || !file.isFile()) {
            JOptionPane.showMessageDialog(frame, "File not found or invalid: " + fileName);
            return false;
        }

        if (openCSV(file)) {
            currentFileName = fileName;
            return true;
        }
        return false;
    }

    private boolean openCSV(File file) {
        // Validate file input
        if (file == null || !file.exists() || !file.isFile()) {
            JOptionPane.showMessageDialog(frame, "Invalid file selected.");
            return false;
        }

        // Clear existing data in the table model
        tableModel.setRowCount(0);

        try (CSVParser parser = new CSVParser(new FileReader(file),
                                            CSVFormat.DEFAULT.builder()
                                                .setHeader() // Automatically treat the first row as header
                                                .setSkipHeaderRecord(false) // Ensure the header is not skipped
                                                .build())) {
        

            // Get header names (columns)
            Map<String, Integer> headerMap = parser.getHeaderMap();
            if (headerMap == null || headerMap.isEmpty()) {
                JOptionPane.showMessageDialog(frame, "No headers found in CSV file.");
                return false;
            }

            // Iterate through records
            for (CSVRecord record : parser) {
                try {
                    // Create an array to hold the row data based on the number of columns
                    String[] data = new String[headerMap.size()];

                    // Populate row data dynamically using header names
                    int index = 0;
                    for (String columnName : headerMap.keySet()) {
                        data[index++] = record.get(columnName);
                    }

                    // Add the row to the table model
                    tableModel.addRow(data);
                } catch (Exception rowException) {
                    // Log row-specific errors and continue
                    System.err.println("Error processing row: " + record + " - " + rowException.getMessage());
                }
            }

        } catch (IOException e) {
            JOptionPane.showMessageDialog(frame, "Error reading file: " + e.getMessage());
            return false;
        } catch (Exception e) {
            JOptionPane.showMessageDialog(frame, "Unexpected error: " + e.getMessage());
            return false;
        }
        return true;
    }


    private void saveCSV() {
        File file = new File(currentFileName);
        if (!file.exists() || !file.isFile()) {
            JOptionPane.showMessageDialog(frame, "File not found or invalid: " + currentFileName);
            return;
        }

        try (BufferedWriter writer = new BufferedWriter(new FileWriter(file));
                    CSVPrinter csvPrinter = new CSVPrinter(writer, CSVFormat.DEFAULT)) {

             // Write the headers
            int columnCount = tableModel.getColumnCount();
            List<String> headers = new ArrayList<>();
            for (int col = 0; col < columnCount; col++) {
                headers.add(tableModel.getColumnName(col));
            }
            csvPrinter.printRecord(headers);

            // Iterate through rows in the table model
            for (int i = 0; i < tableModel.getRowCount(); i++) {
                Vector<?> row = tableModel.getDataVector().elementAt(i);

                // Convert the row data into a list of strings for the CSVPrinter
                List<String> rowData = new ArrayList<>();
                for (Object cell : row) {
                    String cellValue = (cell != null) ? cell.toString() : ""; // Handle null cells gracefully
                    rowData.add(cellValue);
                }

                // Print the row to the CSV file
                csvPrinter.printRecord(rowData);
            }

            JOptionPane.showMessageDialog(frame, "File saved successfully: " + currentFileName);

        } catch (IOException ex) {
            JOptionPane.showMessageDialog(frame, "Error saving file: " + ex.getMessage());
        }
    }


    private void searchDatabase() {
        String searchText[] = searchField.getText().toLowerCase().split("[*]");

        // Create a RowFilter to match rows based on searchText
        RowFilter<DefaultTableModel, Integer> filter = new RowFilter<DefaultTableModel, Integer>() {
            @Override
            public boolean include(Entry<? extends DefaultTableModel, ? extends Integer> entry) {
                // Special case for if searchText is empty
                if (searchText[0] == "") {
                    return true;
                }

                boolean searchTextFound[] = new boolean[searchText.length];

                for (int i = 0; i < tableModel.getColumnCount(); i++) {
                    String cellValue = "";
                    try {
                        cellValue = entry.getStringValue(i).toLowerCase();
                    } catch (Exception e) {
                        // Ignore empty or null cells
                    }
                    
                    for (int j = 0; j < searchText.length; j++) {
                        if (cellValue.contains(searchText[j])) {
                            searchTextFound[j] = true;
                        }
                    }
                }

                for (int i = 0; i < searchText.length; i++)
                {
                    if (searchTextFound[i] == false)
                        return false;  // Hide the row if any of the matches were not found in any of the columns
                }
                return true; // Show the row as default
            }
        };

        // Apply the filter to the TableRowSorter
        TableRowSorter<DefaultTableModel> sorter = new TableRowSorter<>(tableModel);
        sorter.setRowFilter(filter);
        table.setRowSorter(sorter);
    }

    private void addRow() {
        addRow(false);
    }

    private void duplicateRow() {
        addRow(true);
    }

    private void addRow(boolean duplicate) {
        String[] rowData = new String[columnNames.length];
        for (int i = 0; i < columnNames.length; i++) {
            if (duplicate == false) rowData[i] = "";
            else                    rowData[i] = inputFields[i].getText();
        }
        tableModel.addRow(rowData);
        
        // Select the row that was just added
        int newRow = tableModel.getRowCount() - 1; // Index of the new row
        table.setRowSelectionInterval(newRow, newRow);
        table.scrollRectToVisible(table.getCellRect(newRow, 0, true)); // Optional: Scroll to the new row
    }

    private void updateRow() {
        int selectedRow = table.getSelectedRow();

        if (selectedRow != -1) { // Ensure a row is selected
            // Convert the selected row index from the view to the model
            int modelRow = table.getRowSorter().convertRowIndexToModel(selectedRow);

            // Update the model with the values from the input fields
            for (int i = 0; i < columnNames.length; i++) {
                String newValue = inputFields[i].getText(); // Get the value from the input field
                tableModel.setValueAt(newValue, modelRow, i); // Update the table model at the correct index
            }
        } else {
            JOptionPane.showMessageDialog(null, "Please select a row to update.", "No Row Selected", JOptionPane.WARNING_MESSAGE);
        }
    }

    public static void main(String[] args) {
        SwingUtilities.invokeLater(CSVGuiApp::new);
    }
}
